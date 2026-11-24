"""Classify the wrong answers of the NL->Cypher benchmark runs.

This is an automatic, *heuristic* classification. For CypherBench it compares the final query
with the gold query structurally (node labels, relationship types and directions, string
constants, aggregates, EXISTS / NOT / OPTIONAL MATCH, variable-length paths, DISTINCT,
ORDER BY / LIMIT). For MetaQA, which has no gold queries, it compares answer sets. Every failure
gets all the tags that apply and one primary category, the first tag in ``PRIORITY``.
Categories describe *how the query differs*, not who is at fault: a failure is attributed to the
engine only when the gold query itself does not reproduce the gold answer on GQL-Core.

    python benchmark/nl_failure_taxonomy.py
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

RESULTS = Path("benchmark/results")
OUT = RESULTS / "nl_failure_taxonomy.json"
RUNS = {
    "cypherbench": {"model-only": "cypherbench_nl2cypher__gemini_gemini-2.5-flash.json",
                    "direction-corrected": "cypherbench_nl2cypher__gemini_gemini-2.5-flash__corrected.json",
                    "pipeline": "cypherbench_nl2cypher__gemini_gemini-2.5-flash__pipeline.json"},
    "metaqa": {"model-only": "metaqa_nl2cypher__gemini_gemini-2.5-flash.json",
               "direction-corrected": "metaqa_nl2cypher__gemini_gemini-2.5-flash__corrected.json",
               "pipeline": "metaqa_nl2cypher__gemini_gemini-2.5-flash__pipeline.json"},
}

PRIORITY = [
    "syntax error", "semantic validation or runtime error", "timeout",
    "wrong node label", "wrong relationship type", "relationship direction",
    "missing filter", "wrong constant value",
    "EXISTS / NOT / OPTIONAL MATCH logic", "path or traversal shape", "aggregation",
    "missing DISTINCT", "ORDER BY / LIMIT",
    "same shape: different binding or projection",
]

_LABEL = re.compile(r"\(\s*`?\w*`?\s*:\s*`?(\w+)")
_REL = re.compile(r"(<)?-\s*\[\s*`?\w*`?\s*(?::\s*([\w|`]+))?([^\]]*)\]\s*-(>)?")
_STR = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"")
_AGG = re.compile(r"\b(count|sum|avg|min|max|collect)\s*\(", re.I)


_NODE = r"\(\s*`?(\w*)`?\s*(?::\s*`?(\w+)`?)?[^()]*\)"
_TRIPLE = re.compile(_NODE + r"\s*(<)?-\s*\[\s*`?\w*`?\s*(?::\s*([\w|`]+))?[^\]]*\]\s*-(>)?\s*(?=" + _NODE + ")")
_VAR_LABEL = re.compile(r"\(\s*`?(\w+)`?\s*:\s*`?(\w+)")


def triples(q: str) -> list[tuple[str, str, str]]:
    """(source label, type, target label) of every relationship, whichever end it is written from."""
    var_label = dict(_VAR_LABEL.findall(q))
    out = []
    for m in _TRIPLE.finditer(q):
        lv, ll, back, types, fwd, rv, rl = m.groups()
        left, right = ll or var_label.get(lv, "?"), rl or var_label.get(rv, "?")
        for t in (types or "").replace("`", "").split("|"):
            if back and not fwd:
                out.append((right, t, left))
            elif fwd and not back:
                out.append((left, t, right))
            else:  # undirected: order the ends so both spellings compare equal
                a, b = sorted((left, right))
                out.append((a, t, b))
    return sorted(out)


def features(q: str) -> dict:
    low = q.lower()
    rels = []
    for m in _REL.finditer(q):
        for t in (m.group(2) or "").replace("`", "").split("|"):
            rels.append((t, "in" if m.group(1) else "out" if m.group(4) else "any", "*" in (m.group(3) or "")))
    return {
        "labels": sorted(set(_LABEL.findall(q))),
        "rel_types": sorted({t for t, _, _ in rels if t}),
        "triples": triples(q),
        "var_length": any(v for _, _, v in rels),
        "hops": len(rels),
        "strings": sorted({a or b for a, b in _STR.findall(q)}),
        "aggs": sorted(a.lower() for a in _AGG.findall(q)),
        "exists": "exists" in low, "negation": bool(re.search(r"\bnot\b", low)),
        "optional": "optional match" in low,
        "distinct": "distinct" in low, "order": "order by" in low, "limit": bool(re.search(r"\blimit\b", low)),
    }


def _flip(dirs):
    return sorted((t, {"in": "out", "out": "in"}.get(d, d)) for t, d in dirs)


def cypherbench_tags(r: dict) -> list[str]:
    last = (r.get("attempts") or [{}])[-1]
    err = last.get("error") or ""
    if r.get("executable") != 1.0:
        if "timeout" in err.lower() or "timed out" in err.lower():
            return ["timeout"]
        if re.search(r"Unexpected|parse|No terminal|Expected one of", err):
            return ["syntax error"]
        return ["semantic validation or runtime error"]
    p, g = features(r["pred_cypher"] or ""), features(r["gold_cypher"])
    tags = []
    if p["labels"] != g["labels"]:
        tags.append("wrong node label")
    if p["rel_types"] != g["rel_types"]:
        tags.append("wrong relationship type")
    elif set(p["triples"]) != set(g["triples"]) and {(t, frozenset((a, b))) for a, t, b in p["triples"]} == {
            (t, frozenset((a, b))) for a, t, b in g["triples"]}:
        tags.append("relationship direction")  # same relationships between the same labels, reversed
    if p["strings"] != g["strings"]:
        tags.append("missing filter" if set(p["strings"]) < set(g["strings"]) else "wrong constant value")
    if (p["exists"], p["negation"], p["optional"]) != (g["exists"], g["negation"], g["optional"]):
        tags.append("EXISTS / NOT / OPTIONAL MATCH logic")
    if p["var_length"] != g["var_length"] or (p["hops"] != g["hops"] and not g["optional"]):
        tags.append("path or traversal shape")
    if p["aggs"] != g["aggs"]:
        tags.append("aggregation")
    if g["distinct"] and not p["distinct"]:
        tags.append("missing DISTINCT")
    if (p["order"], p["limit"]) != (g["order"], g["limit"]):
        tags.append("ORDER BY / LIMIT")
    return tags or ["same shape: different binding or projection"]


def metaqa_tags(r: dict) -> list[str]:
    if r.get("executable") != 1.0:
        err = ((r.get("attempts") or [{}])[-1].get("error") or "")
        return ["syntax error" if re.search(r"Unexpected|parse|No terminal", err) else
                "semantic validation or runtime error"]
    pred = {str(a).lower() for a in r.get("pred_answers") or []}
    gold = {str(a).lower() for a in r.get("gold_answers") or []}
    if not pred:
        return ["answer: no rows"]
    if pred < gold:
        return ["answer: subset of the gold answers"]
    if pred > gold:
        return ["answer: superset of the gold answers"]
    if pred & gold:
        return ["answer: overlaps the gold answers"]
    return ["answer: disjoint from the gold answers"]


def main() -> None:
    out: dict = {"method": __doc__.strip().splitlines()[0] + " Heuristic; see the module docstring.",
                 "priority": PRIORITY, "runs": {}}
    for bench, runs in RUNS.items():
        for cfg, fname in runs.items():
            d = json.loads((RESULTS / fname).read_text(encoding="utf-8"))
            score = "execution_accuracy" if bench == "cypherbench" else "em"
            fails = [r for r in d["results"] if r[score] != 1.0]
            items = []
            for r in fails:
                tags = cypherbench_tags(r) if bench == "cypherbench" else metaqa_tags(r)
                primary = next((t for t in PRIORITY if t in tags), tags[0])
                rec = {"qid": r["qid"], "primary": primary, "tags": tags}
                if bench == "cypherbench":
                    rec["gold_reproducible_on_engine"] = r.get("gold_reproducible_on_engine")
                items.append(rec)
            key = f"{bench}/{cfg}"
            out["runs"][key] = {
                "file": fname, "questions": len(d["results"]), "failures": len(fails),
                "primary": dict(Counter(i["primary"] for i in items).most_common()),
                "any_tag": dict(Counter(t for i in items for t in i["tags"]).most_common()),
                "failures_whose_gold_query_is_not_reproducible_on_gql_core": sum(
                    1 for i in items if i.get("gold_reproducible_on_engine") is False),
                "items": items,
            }
            print(f"{key:<34} {len(fails):>3} failures  {out['runs'][key]['primary']}")
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
