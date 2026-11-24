"""Layer A: run CypherBench gold Cypher on GQL-Core and compare with Neo4j gold answers.

Every test question has a gold Cypher query and the answer that query produced
on Neo4j (``answer_json``). This script executes each gold query on GQL-Core
over the same graph and scores it with the official execution-accuracy
comparison. A mismatch, an error or a timeout is a failure and is recorded
with its reason.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import re
import time
from pathlib import Path

from benchmark.cypherbench.common import QueryTimeout, avg, breakdown, engine_info, git_commit, load_test, run_with_timeout
from benchmark.cypherbench.download import TEST_GRAPHS, graph_path
from benchmark.cypherbench.loader import load_simplekg
from benchmark.cypherbench.metrics import execution_accuracy, to_hashable

OUT = Path("benchmark/results/cypherbench_engine_parity.json")

_ORDER_RE = re.compile(r"^(?P<head>.*\bRETURN\s+)(?P<proj>.+?)\s+ORDER BY\s+(?P<key>.+?)\s+(?P<dir>ASC|DESC)"
                       r"(?:\s+LIMIT\s+(?P<limit>\d+))?\s*$", re.I | re.S)


def tie_diagnosis(cypher: str, graph, gold: list, timeout_s: float) -> str | None:
    """For an ORDER BY query whose official comparison failed, decide whether the
    mismatch is only the order (or LIMIT pick) among rows with *equal* sort keys.

    openCypher leaves the relative order of tied rows undefined, so Neo4j's gold
    order among ties is arbitrary. We re-run the query exposing the sort key
    (without LIMIT), look up every gold row's key, and check that the gold rows
    form a valid ordering with the same key sequence as ours. Returns
    "tie_equivalent", "not_tie" or None when the query shape is not analysable.
    The official score is never changed by this diagnosis.
    """
    m = _ORDER_RE.match(cypher.strip())
    if not m:
        return None
    key, direction = m.group("key"), m.group("dir")
    probe = f"{m.group('head')}{m.group('proj')}, {key} AS __sort_key ORDER BY {key} {direction}"
    try:
        rows = run_with_timeout(probe, graph, timeout_s)
    except Exception:  # noqa: BLE001
        return None
    # Multiset of (row values, sort key) pairs; duplicate names with different keys are
    # resolved by consuming exactly the pair the position requires.
    available: dict[tuple, int] = {}
    ours = []
    for r in rows:
        vals = tuple(to_hashable(v) for k, v in r.items() if k != "__sort_key")
        k = to_hashable(r["__sort_key"])
        available[(vals, k)] = available.get((vals, k), 0) + 1
        ours.append(k)
    limit = int(m.group("limit")) if m.group("limit") else None
    expected = ours[:limit] if limit is not None else ours
    if len(gold) != len(expected):
        return "not_tie"
    for row, k in zip(gold, expected):
        pair = (tuple(to_hashable(v) for v in row), k)
        if available.get(pair, 0) == 0:
            return "not_tie"
        available[pair] -= 1
    return "tie_equivalent"


def evaluate_graph(graph_name: str, items: list[dict], timeout_s: float) -> tuple[list[dict], dict]:
    t0 = time.perf_counter()
    graph, _ = load_simplekg(graph_path(graph_name))
    load_s = time.perf_counter() - t0
    info = {"nodes": len(graph._nodes), "edges": len(graph._edges), "load_seconds": round(load_s, 2)}
    print(f"[{graph_name}] loaded {info['nodes']:,} nodes / {info['edges']:,} edges in {load_s:.1f}s; "
          f"{len(items)} questions", flush=True)

    out = []
    for i, it in enumerate(items, 1):
        rec = {
            "qid": it["qid"],
            "graph": graph_name,
            "match_category": it["from_template"]["match_category"],
            "return_pattern_id": it["from_template"]["return_pattern_id"],
            "gold_cypher": it["gold_cypher"],
            "execution_accuracy": 0.0,
            "status": "",
        }
        t = time.perf_counter()
        try:
            rows = run_with_timeout(it["gold_cypher"], graph, timeout_s)
            rec["execution_accuracy"] = execution_accuracy(rows, it["answer_json"], it["gold_cypher"])
            rec["status"] = "match" if rec["execution_accuracy"] == 1.0 else "mismatch"
            if rec["status"] == "mismatch":
                gold = json.loads(it["answer_json"])
                rec["detail"] = {"got_rows": len(rows), "gold_rows": len(gold),
                                 "got_sample": [[str(v) for v in r.values()] for r in rows[:3]],
                                 "gold_sample": gold[:3]}
                if "order by" in it["gold_cypher"].lower():
                    rec["tie_diagnosis"] = tie_diagnosis(it["gold_cypher"], graph, gold, timeout_s)
        except QueryTimeout as exc:
            rec["status"], rec["detail"] = "timeout", str(exc)
        except Exception as exc:  # noqa: BLE001
            rec["status"], rec["detail"] = "error", f"{type(exc).__name__}: {exc}"[:500]
        rec["latency_ms"] = round((time.perf_counter() - t) * 1000, 2)
        out.append(rec)
        if i % 50 == 0:
            print(f"  {i}/{len(items)}  EX so far {avg([r['execution_accuracy'] for r in out]):.4f}", flush=True)
    del graph
    gc.collect()
    return out, info


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--graphs", nargs="+", default=TEST_GRAPHS, choices=TEST_GRAPHS)
    ap.add_argument("--timeout", type=float, default=120.0, help="per-query timeout (s); the official eval uses 120")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--merge", type=Path, nargs="+", default=None,
                    help="combine results files of separate runs (e.g. one process per graph, "
                         "to bound memory) into --out instead of running queries")
    args = ap.parse_args()

    results, graphs_info = [], {}
    if args.merge:
        parts = [json.loads(p.read_text(encoding="utf-8")) for p in args.merge]
        engines = {json.dumps(p["engine"], sort_keys=True) for p in parts}
        if len(engines) != 1 or len({p["timeout_seconds"] for p in parts}) != 1:
            raise SystemExit("the files to merge were produced by different engines or settings")
        for p in parts:
            results += p["results"]
            graphs_info.update(p["graphs"])
    else:
        test = load_test()
        for g in args.graphs:
            items = [x for x in test if x["graph"] == g]
            recs, info = evaluate_graph(g, items, args.timeout)
            results += recs
            graphs_info[g] = info
            print(f"[{g}] execution accuracy vs Neo4j gold: {avg([r['execution_accuracy'] for r in recs]):.4f}", flush=True)

    status_counts: dict[str, int] = {}
    for r in results:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
    tie_equiv = sum(1 for r in results if r.get("tie_diagnosis") == "tie_equivalent")
    summary = {
        "benchmark": "CypherBench test split (megagonlabs/cypherbench), gold Cypher executed on GQL-Core",
        "metric": "official CypherBench execution accuracy vs Neo4j gold answers (answer_json)",
        "engine": parts[0]["engine"] if args.merge else engine_info(),
        "git_commit": parts[0]["git_commit"] if args.merge else git_commit(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "timeout_seconds": parts[0]["timeout_seconds"] if args.merge else args.timeout,
        **({"merged_from": len(args.merge)} if args.merge else {}),
        # Row order among ORDER BY ties depends on set iteration order; pin it for reproducibility.
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        "graphs": graphs_info,
        "total": len(results),
        "execution_accuracy": avg([r["execution_accuracy"] for r in results]),
        "status_counts": status_counts,
        "mismatches_only_in_tied_order": tie_equiv,
        "execution_accuracy_counting_tied_order_as_match": avg(
            [1.0 if (r["execution_accuracy"] == 1.0 or r.get("tie_diagnosis") == "tie_equivalent") else 0.0
             for r in results]),
        **breakdown(results, "execution_accuracy"),
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
