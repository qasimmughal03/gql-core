"""Verify a CypherBench gold-query results file and analyse every query that did not match.

Checks the merged ``cypherbench_engine_parity.json`` against the official test split: every
question present exactly once, every graph complete, the engine stamp recorded. Then, for every
query whose official comparison failed, re-runs the gold query on the same engine, keeps the full
gold and actual rows, and analyses ORDER BY ties:

* ``tie_order_only``: the same rows, and the same sequence of sort-key values, in a different order
  among rows whose sort keys are equal. openCypher leaves that order undefined.
* ``tie_limit_boundary``: LIMIT cuts through a group of rows with equal sort keys, so which of them
  are returned is undefined; ours and Neo4j's are both valid.
* ``not_tie``: a real difference in the rows or in the key sequence.

Two metrics are reported: **strict**, the official CypherBench execution accuracy (row order
counts whenever the query has ORDER BY), and **semantic**, which also accepts the two tie classes
above and nothing else. The official comparator is never changed.

Run with the installed package, after the gold-query run:

    python benchmark/run_published.py benchmark.cypherbench.verify_engine_parity
"""

from __future__ import annotations

import argparse
import gc
import json
import time
from collections import Counter
from pathlib import Path

from benchmark.cypherbench.common import engine_info, load_test, run_with_timeout
from benchmark.cypherbench.download import graph_path
from benchmark.cypherbench.loader import load_simplekg
from benchmark.cypherbench.metrics import execution_accuracy, result_eq, to_hashable
from benchmark.cypherbench.run_engine_parity import _ORDER_RE

IN = Path("benchmark/results/cypherbench_engine_parity.json")
OUT = Path("benchmark/results/cypherbench_engine_parity_failures.json")


def _plain(v):
    v = to_hashable(v)
    return list(map(_plain, v)) if isinstance(v, tuple) else v


def analyse_order(cypher: str, graph, gold: list, timeout_s: float) -> dict:
    m = _ORDER_RE.match(cypher.strip())
    if not m:
        return {"order_analysis": "not_analysable", "reason": "ORDER BY shape not supported by the probe"}
    key, direction = m.group("key"), m.group("dir")
    limit = int(m.group("limit")) if m.group("limit") else None
    probe = f"{m.group('head')}{m.group('proj')}, {key} AS __sort_key ORDER BY {key} {direction}"
    rows = run_with_timeout(probe, graph, timeout_s)
    pairs = [(tuple(to_hashable(v) for k, v in r.items() if k != "__sort_key"), to_hashable(r["__sort_key"]))
             for r in rows]
    keys = [k for _, k in pairs]
    expected_keys = keys[:limit] if limit is not None else keys
    info = {"order_by": key, "direction": direction, "limit": limit,
            "rows_before_limit": len(rows), "distinct_sort_keys_returned": len(set(expected_keys))}
    if len(gold) != len(expected_keys):
        return {**info, "order_analysis": "not_tie", "reason": "different number of rows"}
    # Each gold row, paired with the sort key its position requires, must be one of our rows.
    available = Counter(pairs)
    for pos, row in enumerate(gold):
        pair = (tuple(to_hashable(v) for v in row), expected_keys[pos])
        if available[pair] == 0:
            return {**info, "order_analysis": "not_tie",
                    "reason": f"gold row {pos} is not among our rows with the sort key its position requires"}
        available[pair] -= 1
    groups = Counter(expected_keys)
    info["tied_rows_returned"] = sum(n for n in groups.values() if n > 1)
    info["largest_tie_group"] = max(groups.values()) if groups else 0
    boundary = limit is not None and len(keys) > limit and keys[limit - 1] == keys[limit]
    if boundary:
        info["tie_group_at_limit"] = {"sort_key": _plain(keys[limit - 1]),
                                      "rows_with_that_key": keys.count(keys[limit - 1]),
                                      "of_which_returned": expected_keys.count(keys[limit - 1])}
    return {**info, "order_analysis": "tie_limit_boundary" if boundary else "tie_order_only"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", type=Path, default=IN)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()

    res = json.loads(args.results.read_text(encoding="utf-8"))
    test = load_test()
    by_qid = {t["qid"]: t for t in test}
    qids = [r["qid"] for r in res["results"]]
    checks = {
        "official_test_questions": len(test),
        "evaluated": len(qids),
        "unique_qids": len(set(qids)),
        "duplicates": [q for q, n in Counter(qids).items() if n > 1],
        "missing": sorted(set(by_qid) - set(qids)),
        "unexpected": sorted(set(qids) - set(by_qid)),
        "graphs": dict(sorted(Counter(r["graph"] for r in res["results"]).items())),
        "graphs_expected": dict(sorted(Counter(t["graph"] for t in test).items())),
        "graph_mismatch": [r["qid"] for r in res["results"] if by_qid.get(r["qid"], {}).get("graph") != r["graph"]],
        "gold_cypher_mismatch": [r["qid"] for r in res["results"]
                                 if by_qid.get(r["qid"], {}).get("gold_cypher") != r["gold_cypher"]],
        "status_counts": dict(Counter(r["status"] for r in res["results"])),
        "engine": res.get("engine"),
        "verifier_engine": engine_info(),
    }
    checks["complete"] = (checks["evaluated"] == checks["unique_qids"] == len(test) and not checks["missing"]
                          and not checks["unexpected"] and not checks["graph_mismatch"]
                          and not checks["gold_cypher_mismatch"] and checks["graphs"] == checks["graphs_expected"])
    print(json.dumps({k: v for k, v in checks.items() if k not in ("engine", "verifier_engine")}, indent=2))

    failing = [r for r in res["results"] if r["execution_accuracy"] != 1.0]
    analysed = []
    for g in sorted({r["graph"] for r in failing}):
        graph, _ = load_simplekg(graph_path(g))
        for r in (x for x in failing if x["graph"] == g):
            item = by_qid[r["qid"]]
            gold = json.loads(item["answer_json"])
            rec = {"qid": r["qid"], "graph": g, "status": r["status"], "gold_cypher": item["gold_cypher"],
                   "nl_question": item.get("nl_question"), "match_category": r["match_category"],
                   "return_pattern_id": r["return_pattern_id"], "gold_rows": gold}
            try:
                t0 = time.perf_counter()
                try:
                    rows = run_with_timeout(item["gold_cypher"], graph, args.timeout)
                finally:
                    rec["rerun_latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                # The re-run is scored with the same official comparison as the full run.
                rec["rerun_execution_accuracy"] = execution_accuracy(rows, item["answer_json"], item["gold_cypher"])
                rec["actual_rows"] = [[_plain(v) for v in row.values()] for row in rows]
                got = [tuple(to_hashable(v) for v in row.values()) for row in rows]
                want = [tuple(to_hashable(v) for v in row) for row in gold]
                rec["same_rows_ignoring_order"] = result_eq(want, got, order_matters=False)
                if "order by" in item["gold_cypher"].lower():
                    rec.update(analyse_order(item["gold_cypher"], graph, gold, args.timeout))
                else:
                    rec["order_analysis"] = "no_order_by"
            except Exception as exc:  # noqa: BLE001
                rec["rerun_error"] = f"{type(exc).__name__}: {exc}"[:300]
            if r["status"] == "timeout":
                rec["category"] = ("timeout in the full run; matches when re-run alone"
                                   if rec.get("rerun_execution_accuracy") == 1.0 else "timeout")
            elif rec.get("order_analysis") in ("tie_order_only", "tie_limit_boundary"):
                rec["category"] = "ordering among tied rows"
            else:
                rec["category"] = "needs review"
            analysed.append(rec)
            print(f"[{g}] {r['qid'][:8]} {rec.get('order_analysis', rec.get('rerun_error'))}", flush=True)
        del graph
        gc.collect()

    total = len(res["results"])
    strict = sum(1 for r in res["results"] if r["execution_accuracy"] == 1.0)
    tie_ok = sum(1 for a in analysed if a["category"] == "ordering among tied rows")
    rerun_ok = sum(1 for a in analysed if a["category"] == "timeout in the full run; matches when re-run alone")
    agree = {a["qid"]: (a.get("order_analysis") in ("tie_order_only", "tie_limit_boundary"))
             == (next(r for r in res["results"] if r["qid"] == a["qid"]).get("tie_diagnosis") == "tie_equivalent")
             for a in analysed}
    summary = {
        "benchmark": "CypherBench test split (megagonlabs/cypherbench, Apache-2.0), gold Cypher on GQL-Core",
        "results_file": str(args.results).replace("\\", "/"),
        "engine": res.get("engine"),
        "completeness": checks,
        "strict": {"matches": strict, "total": total, "accuracy": round(strict / total, 4),
                   "definition": "the official CypherBench execution accuracy of the full run, as recorded"},
        "strict_with_timeouts_rerun_alone": {
            "matches": strict + rerun_ok, "total": total, "accuracy": round((strict + rerun_ok) / total, 4),
            "definition": "strict, after re-running each timed-out query on its own with the same engine, "
                          "graph and 120 s limit"},
        "semantic": {"matches": strict + rerun_ok + tie_ok, "total": total,
                     "accuracy": round((strict + rerun_ok + tie_ok) / total, 4),
                     "definition": "strict_with_timeouts_rerun_alone plus mismatches that are only the order, "
                                   "or the LIMIT pick, among rows with equal ORDER BY keys"},
        "failures": len(analysed),
        "failure_categories": dict(Counter(a["category"] for a in analysed)),
        "order_analysis": dict(Counter(a.get("order_analysis", "rerun_error") for a in analysed)),
        "agrees_with_harness_tie_diagnosis": all(agree.values()),
        "analysed": analysed,
    }
    args.out.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("analysed", "completeness")}, indent=2))
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
