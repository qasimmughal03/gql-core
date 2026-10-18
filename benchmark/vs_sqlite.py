"""Benchmark harness: GQL-Core vs SQLite.

For each paired query in benchmark.queries.QUERIES:
  1. Run both engines once to capture results (correctness check).
  2. Time each with timeit.repeat (number=1, repeat=N).
  3. Record median, p95, mean, stdev.
  4. Compute expressibility metrics.

Output: benchmark/results/results.json with a row per query plus a meta
block (timestamp, hardware, git rev, fixture/corpus stats).
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import sqlite3
import statistics
import subprocess
import sys
import time
import timeit
from pathlib import Path
from typing import Any

from graph.store import PropertyGraph
from ingestion.cricsheet_parser import CricsheetParser
from ingestion.validator import ShapeValidator
from query.executor import execute, run as run_cypher
from query.parser import parse
from query.planner import plan as plan_query
from query.semantic import validate_query
from benchmark.queries import QUERIES, expressibility
from benchmark.logical_reasoning import (
    LR_QUERIES,
    expressibility as lr_expressibility,
)
from scripts.build_sqlite_mirror import build_mirror

DEFAULT_RESULTS = Path("benchmark/results/results.json")


def _resolve_start_id(query: dict, graph: PropertyGraph) -> dict:
    """Substitute the `{start_id}` placeholder with a real Delivery id.

    Picks any node whose label is Delivery so the query never points at a
    non-existent id (which would create the Cypher-empty vs SQL-zero-row
    semantic mismatch noted in the README). Returns a shallow-copied query
    with the placeholder filled in; the original dict is untouched.
    """
    if not query.get("needs_start_id"):
        return query
    delivery = _select_start_delivery(graph)
    if delivery is None:
        return query
    start_id = delivery.id
    q = dict(query)
    q["cypher"] = q["cypher"].format(start_id=start_id)
    q["sql"] = q["sql"].format(start_id=start_id)
    q["_resolved_start_id"] = start_id
    return q


def _select_start_delivery(graph: PropertyGraph):
    """Pick a deterministic Delivery node with at least one successor when possible."""
    deliveries = sorted(graph.nodes_by_label("Delivery"), key=lambda n: n.id)
    for delivery in deliveries:
        if any(graph.neighbors(delivery.id, label="NEXT_DELIVERY", direction="out")):
            return delivery
    return deliveries[0] if deliveries else None


def _git_rev() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip() or "unknown"
    except Exception:
        pass
    return "unknown"


def _git_dirty() -> bool | None:
    try:
        out = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True,
            text=True,
            check=False,
        )
        if out.returncode == 0:
            return bool(out.stdout.strip())
    except Exception:
        pass
    return None


def _environment_meta() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
    }


def _methodology_meta() -> dict:
    return {
        "tracks": [
            {
                "name": "fixture_gold_oracle",
                "source": "tests/test_regression.py",
                "purpose": "Hand-computed fixture answers catch shared graph/SQL bugs.",
            },
            {
                "name": "full_corpus_sql_parity",
                "source": "benchmark.vs_sqlite + benchmark.run_nl_benchmark",
                "purpose": "GQL-Core and SQLite row-set equality on the same materialized corpus.",
            },
            {
                "name": "expressibility",
                "source": "benchmark query metadata",
                "purpose": "Structural query-size and recursive-SQL indicators.",
            },
            {
                "name": "nl_to_gql_model_accuracy",
                "source": "benchmark.run_suite_benchmark",
                "purpose": "Model translation accuracy against hidden SQL oracles.",
            },
        ],
        "oracle_note": (
            "SQLite parity validates executor agreement with a mirror derived from the "
            "graph; independent fixture gold tests are required to catch shared ingestion "
            "or modeling errors."
        ),
        "timing_scopes": {
            "cypher": "parse + semantic validation + plan + execute",
            "cypher_parse_plan": "parse + semantic validation + plan only",
            "cypher_execute": "execute a prebuilt plan only",
            "sql": "SQLite execute + fetchall on an indexed mirror",
        },
    }


def _prepare_cypher(source: str, graph: PropertyGraph):
    parsed = parse(source)
    validate_query(parsed)
    return plan_query(parsed, graph)


def _canonical_rows(
    rows: list,
    key_columns: tuple[str, ...],
    distinct: bool = False,
) -> list[tuple]:
    """Return a sorted list-of-tuples for deterministic comparison.

    GQL rows are dicts keyed by the alias chosen by the model, which may differ
    from the SQL alias in key_columns.  Named extraction is used only when ALL
    expected keys are present in the dict; otherwise we fall back to positional
    (dict insertion order = RETURN clause order) to survive alias mismatches.
    SQL rows are plain tuples — always positional.
    """
    canon: list[tuple] = []
    for r in rows:
        if isinstance(r, dict):
            if all(c in r for c in key_columns):
                canon.append(tuple(r[c] for c in key_columns))
            else:
                # Model used different alias names — compare positionally.
                canon.append(tuple(r.values()))
        else:
            canon.append(tuple(r))
    if distinct:
        canon = list(dict.fromkeys(canon))
    canon.sort(key=lambda t: tuple((v is None, v if v is not None else "") for v in t))
    return canon


def _rows_equal(a: list[tuple], b: list[tuple]) -> bool:
    if len(a) != len(b):
        return False
    for ra, rb in zip(a, b):
        if len(ra) != len(rb):
            return False
        for va, vb in zip(ra, rb):
            if isinstance(va, float) or isinstance(vb, float):
                if va is None or vb is None:
                    if va != vb:
                        return False
                elif not math.isclose(va, vb, rel_tol=1e-6):
                    return False
            elif va != vb:
                return False
    return True


def _time(fn, iters: int) -> dict[str, float]:
    samples = timeit.repeat(fn, number=1, repeat=iters)
    return {
        "median_ms": round(statistics.median(samples) * 1000, 4),
        "p95_ms": round(sorted(samples)[max(0, int(0.95 * iters) - 1)] * 1000, 4),
        "mean_ms": round(statistics.mean(samples) * 1000, 4),
        "stdev_ms": round(statistics.stdev(samples) * 1000, 4) if iters > 1 else 0.0,
        "iters": iters,
    }


def _run_class(
    queries: list[dict],
    expressibility_fn,
    graph: PropertyGraph,
    cursor,
    conn,
    iters: int,
) -> list[dict]:
    rows_out: list[dict] = []
    for raw_q in queries:
        q = _resolve_start_id(raw_q, graph)
        cypher_plan = _prepare_cypher(q["cypher"], graph)
        cypher_rows = execute(cypher_plan, graph)
        sql_rows = cursor.execute(q["sql"]).fetchall()
        is_distinct = "DISTINCT" in q.get("sql", "").upper()
        canon_cypher = _canonical_rows(cypher_rows, q["key_columns"], distinct=is_distinct)
        canon_sql = _canonical_rows(sql_rows, q["key_columns"])
        correct = _rows_equal(canon_cypher, canon_sql)

        # Warm up once each to avoid first-call effects.
        run_cypher(q["cypher"], graph)
        execute(cypher_plan, graph)
        cursor.execute(q["sql"]).fetchall()

        cypher_timing = _time(lambda q=q: run_cypher(q["cypher"], graph), iters)
        cypher_parse_plan_timing = _time(
            lambda q=q: _prepare_cypher(q["cypher"], graph), iters
        )
        cypher_execute_timing = _time(
            lambda plan_obj=cypher_plan: execute(plan_obj, graph), iters
        )
        sql_timing = _time(lambda q=q: conn.cursor().execute(q["sql"]).fetchall(), iters)

        entry = {
            "name": q["name"],
            "purpose": q["purpose"],
            "row_count": len(canon_cypher),
            "result_correct": correct,
            "cypher": cypher_timing,
            "cypher_parse_plan": cypher_parse_plan_timing,
            "cypher_execute": cypher_execute_timing,
            "sql": sql_timing,
            "expressibility": expressibility_fn(q),
        }
        if "_resolved_start_id" in q:
            entry["resolved_start_id"] = q["_resolved_start_id"]
        rows_out.append(entry)
    return rows_out


def benchmark(graph: PropertyGraph, db_path: Path, *, iters: int = 100) -> dict:
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    direct = _run_class(QUERIES, expressibility, graph, cursor, conn, iters)
    reasoning = _run_class(LR_QUERIES, lr_expressibility, graph, cursor, conn, iters)
    conn.close()
    return {
        "meta": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "git_rev": _git_rev(),
            "git_dirty": _git_dirty(),
            "iters": iters,
            "environment": _environment_meta(),
            "graph_stats": graph.stats(),
            "methodology": _methodology_meta(),
        },
        "direct_queries": direct,
        "logical_reasoning": reasoning,
    }


def _load_graph(data_dir: Path, shapes: Path) -> PropertyGraph:
    g = PropertyGraph()
    p = CricsheetParser(g, ShapeValidator(shapes))
    for f in sorted(data_dir.glob("*.json")):
        try:
            p.ingest_file(f)
        except Exception as exc:
            print(f"[warn] {f}: {exc}", file=sys.stderr)
    return g


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=Path("data/pakistan"))
    ap.add_argument("--shapes", type=Path, default=Path("ontology/shapes.yaml"))
    ap.add_argument("--db", type=Path, default=Path("data/cricket.db"))
    ap.add_argument("--out", type=Path, default=DEFAULT_RESULTS)
    ap.add_argument("--iters", type=int, default=100)
    args = ap.parse_args(argv)

    if not args.data.exists() or not any(args.data.glob("*.json")):
        # Fall back to the test fixtures so the harness has something to run on.
        fallback = Path("tests/fixtures")
        print(
            f"[warn] {args.data} has no JSON; falling back to {fallback}",
            file=sys.stderr,
        )
        args.data = fallback

    print(f"[load] ingesting {args.data}", file=sys.stderr)
    graph = _load_graph(args.data, args.shapes)
    print(f"[load] {graph.stats()}", file=sys.stderr)

    print(f"[mirror] writing {args.db}", file=sys.stderr)
    conn = build_mirror(graph, args.db)
    conn.close()

    print(f"[benchmark] iters={args.iters}", file=sys.stderr)
    out = benchmark(graph, args.db, iters=args.iters)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, default=str))
    print(f"[done] wrote {args.out}", file=sys.stderr)

    # Console summary.
    print(json.dumps(
        {"direct_queries": out["direct_queries"], "logical_reasoning": out["logical_reasoning"]},
        indent=2,
        default=str,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
