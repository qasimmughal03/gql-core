"""Evaluate GQL-Core grammar coverage against GQLBench's 25,332 queries.

Measures: parse success rate, failure reasons by category, coverage by
query feature (aggregation, multi-hop, RPQ, etc.).
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

# Use our parser directly
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lark import UnexpectedToken, UnexpectedCharacters, UnexpectedEOF

from gql_core.query.parser import parse as gql_parse


def normalize_gql(gql: str) -> str | None:
    """Normalize a GQLBench Cypher query to GQL-Core syntax.

    Returns None if the query uses features we fundamentally cannot support.
    """
    # Skip queries with unsupported multi-clause / procedure features
    upper = gql.upper()
    if re.search(r'\bWITH\b', upper):
        return None  # multi-clause WITH
    if re.search(r'\bCALL\b', upper):
        return None  # procedure calls
    if re.search(r'\bLET\b', upper):
        return None  # LET assignment
    if re.search(r'\bCOLLECT\b', upper):
        return None  # subquery COLLECT
    if re.search(r'DISTINCT', upper):
        return None  # COUNT(DISTINCT ...) not supported
    if re.search(r'\bUNION\b', upper):
        return None  # UNION not supported
    if re.search(r'\bOPTIONAL\b', upper):
        return None  # OPTIONAL MATCH not supported
    if "=~" in gql:
        return None  # regex match operator
    if re.search(r'\bEXISTS\b', upper):
        return None  # EXISTS subquery
    if re.search(r'\bCASE\b', upper):
        return None  # CASE expression

    # Normalizations
    # 1. Strip backtick quoting: `identifier` -> identifier
    normalized = re.sub(r'`([^`]+)`', r'\1', gql)

    # 2. COUNT(*) -> COUNT(_) (use underscore as dummy var)
    normalized = re.sub(r'COUNT\(\*\)', 'COUNT(_)', normalized)

    # 3. <> -> !=
    normalized = normalized.replace('<>', '!=')

    # 4. Fix node patterns that lost their variable:
    #    MATCH (:Label) needs a variable -> MATCH (_x:Label)
    #    But only if there's no variable before the colon
    normalized = re.sub(r'\(:(\w+)', r'(_:\1', normalized)

    # 5. Fix the special pattern in GQLBench: MATCH (t2:Label)-[r:REL]->(t1:Label)
    #    This is actually our exact syntax, just with backticks removed

    # 6. IS NULL DESC in ORDER BY -> remove IS NULL (our engine doesn't support NULL ordering)
    normalized = re.sub(r'\s+IS\s+NULL\s+(DESC|ASC)', r' \1', normalized, flags=re.IGNORECASE)

    # 7. Remove trailing semicolons
    normalized = normalized.rstrip(';').strip()

    # 8. Capitalize labels: our grammar requires PascalCase labels
    #    (:club) -> (:Club), but preserve variable names
    #    Match label after colon that starts with lowercase
    def capitalize_label(m):
        prefix = m.group(1)  # : or :` (already stripped backticks)
        label = m.group(2)
        return prefix + label[0].upper() + label[1:]
    normalized = re.sub(r'(:)([a-z][a-zA-Z0-9_]*)', capitalize_label, normalized)

    # 9. Fix relation labels with lowercase: -[r:plays_for]-> -> -[r:Plays_for]->
    def capitalize_rel_label(m):
        prefix = m.group(1)
        label = m.group(2)
        suffix = m.group(3)
        return prefix + label[0].upper() + label[1:] + suffix
    normalized = re.sub(r'(-\[[a-zA-Z_0-9]*:)([a-z][a-zA-Z0-9_]*)([\]-])', capitalize_rel_label, normalized)

    # 10. Handle MATCH with only backtick-removed labels at start of line after MATCH
    #     Fix: ensure node patterns have variables
    #     MATCH (:Label) -> MATCH (_:Label)
    normalized = re.sub(r'MATCH\s+\(:', r'MATCH (_:', normalized)

    # 11. ORDER BY before RETURN (GQLBench puts it in various orders)
    #     Our grammar requires: MATCH ... WHERE ... RETURN ... ORDER BY ... LIMIT
    #     GQLBench sometimes has: MATCH ... ORDER BY ... RETURN ...
    #     This is a syntax error in our grammar
    order_by_match = re.search(r'\bORDER\s+BY\b', normalized, re.IGNORECASE)
    return_match = re.search(r'\bRETURN\b', normalized, re.IGNORECASE)
    if order_by_match and return_match and order_by_match.start() < return_match.start():
        # ORDER BY appears before RETURN — swap them
        order_clause = normalized[order_by_match.start():return_match.start()].strip()
        # Extract LIMIT from after ORDER BY if present
        limit_match = re.search(r'\s+LIMIT\s+\d+', order_clause, re.IGNORECASE)
        if limit_match:
            limit_clause = limit_match.group(0)
            order_clause = order_clause[:limit_match.start()] + order_clause[limit_match.end():]
        else:
            limit_clause = ''
        ret_part = normalized[return_match.start():].strip()
        # Remove LIMIT from return part if present
        ret_limit = re.search(r'\s+LIMIT\s+\d+', ret_part, re.IGNORECASE)
        if ret_limit:
            if not limit_clause:
                limit_clause = ret_limit.group(0)
            ret_part = ret_part[:ret_limit.start()] + ret_part[ret_limit.end():]
        before_order = normalized[:order_by_match.start()].strip()
        normalized = before_order + ' ' + ret_part + ' ' + order_clause + ' ' + limit_clause
        normalized = ' '.join(normalized.split())  # collapse whitespace

    # 12. Replace single-quoted strings with double-quoted (our grammar uses double quotes)
    normalized = normalized.replace("'", '"')

    return normalized


def classify_query(gql: str) -> list[str]:
    """Classify a GQL query into feature categories."""
    features = []
    upper = gql.upper()
    if "COUNT(" in upper or "SUM(" in upper or "AVG(" in upper or "MIN(" in upper or "MAX(" in upper:
        features.append("aggregation")
    if "ORDER BY" in upper:
        features.append("order_by")
    if "LIMIT" in upper:
        features.append("limit")
    if gql.count("-[") >= 2 or gql.count("]-") >= 2:
        features.append("multi_hop")
    if "WHERE" in upper:
        features.append("filter")
    if re.search(r'\bAND\b', upper) and "WHERE" not in upper:
        features.append("multi_pattern")  # comma patterns
    if "*" in gql and ("]-" in gql or "-[" in gql):
        features.append("rpq")
    if "!=" in gql or " NOT " in upper:
        features.append("negation")
    if "," in gql.split("MATCH")[-1].split("RETURN")[0]:
        features.append("multi_pattern")
    if " IS NULL" in upper or " IS NOT NULL" in upper:
        features.append("is_null")
    if not features:
        features.append("simple_lookup")
    return features


def classify_error(exc: Exception) -> str:
    """Classify a parse error into a human-readable reason."""
    msg = str(exc)
    if isinstance(exc, UnexpectedToken):
        token = str(exc.token) if exc.token else ""
        # Extract the unexpected token value
        if "IS" in token and "NULL" in msg:
            return "IS NULL / IS NOT NULL (unsupported)"
        if "DISTINCT" in msg.upper():
            return "DISTINCT (unsupported)"
        if "CASE" in msg.upper() or "WHEN" in msg.upper():
            return "CASE/WHEN (unsupported)"
        if "IN " in token or " IN" in token:
            return "IN operator (unsupported)"
        if "`" in token:
            return f"backtick identifier: {token[:40]}"
        if "(" in token and ")" not in token:
            return f"unexpected token: {token[:40]}"
        if "->" not in msg and "<-" not in msg and "-[" not in msg:
            return f"unexpected token: {token[:60]}"
        return f"unexpected token: {token[:60]}"
    if isinstance(exc, UnexpectedCharacters):
        return f"lexer error: {msg[:80]}"
    if isinstance(exc, UnexpectedEOF):
        return "unexpected EOF"
    return f"other: {type(exc).__name__}: {msg[:80]}"


def evaluate(data_path: str, max_queries: int | None = None):
    """Parse all GQLBench queries against GQL-Core grammar."""
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if max_queries:
        data = data[:max_queries]

    results = {
        "total": len(data),
        "parsed": 0,
        "failed": 0,
        "features": Counter(),
        "passed_features": Counter(),
        "failed_features": Counter(),
        "error_types": Counter(),
        "dialects": Counter(),
        "by_db": Counter(),
        "failures": [],
    }

    print(f"Evaluating {len(data)} queries from {Path(data_path).name}...")
    for i, entry in enumerate(data):
        gql = entry["gql_statement"]
        dialect = entry.get("gql_dialect", "unknown")
        db_id = entry.get("db_id", "unknown")
        features = classify_query(gql)
        results["dialects"][dialect] += 1
        results["by_db"][db_id] += 1

        for f in features:
            results["features"][f] += 1

        try:
            normalized = normalize_gql(gql)
            if normalized is None:
                results["failed"] += 1
                results["error_types"]["unsupported feature (WITH/DISTINCT/COLLECT/etc)"] += 1
                for f in features:
                    results["failed_features"][f] += 1
            else:
                gql_parse(normalized)
                results["parsed"] += 1
                for f in features:
                    results["passed_features"][f] += 1
        except Exception as exc:
            results["failed"] += 1
            error_cat = classify_error(exc)
            results["error_types"][error_cat] += 1
            for f in features:
                results["failed_features"][f] += 1
            if len(results["failures"]) < 200:
                results["failures"].append({
                    "db": db_id,
                    "gql": gql[:200],
                    "features": features,
                    "error": error_cat,
                })

        if (i + 1) % 5000 == 0:
            pct = 100 * results["parsed"] / (i + 1)
            print(f"  {i+1}/{len(data)}: {results['parsed']} parsed ({pct:.1f}%)")

    pct = 100 * results["parsed"] / results["total"]
    print(f"\n  FINAL: {results['parsed']}/{results['total']} parsed ({pct:.1f}%)")
    print(f"  {results['failed']} failed")

    print(f"\n  Error breakdown:")
    for reason, count in results["error_types"].most_common(15):
        print(f"    {reason}: {count}")

    print(f"\n  Feature coverage (parsed / total):")
    for feat in sorted(results["features"].keys()):
        total = results["features"][feat]
        parsed = results["passed_features"][feat]
        pct_feat = 100 * parsed / total if total else 0
        print(f"    {feat:<20s}: {parsed:>5}/{total:<5} ({pct_feat:.0f}%)")

    return results


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/tmp/gqlbench/benchmark_data_new/nl_gql/test.json")
    ap.add_argument("--max", type=int, default=None, help="Limit queries for quick testing")
    ap.add_argument("--out", default="benchmark/results/gqlbench_eval.json")
    args = ap.parse_args()

    results = evaluate(args.data, args.max)

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Convert Counter to dict for JSON
    out = {k: dict(v) if isinstance(v, Counter) else v for k, v in results.items()}
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {out_path}")
