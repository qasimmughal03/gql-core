"""Re-run the gold queries that timed out, without a time limit, and score them officially.

A timeout says a query did not finish within 120 s on the machine at the time; it does not say
whether the answer is right. This re-runs each timed-out query of a results file to completion
with the same engine, scores it with the official comparison, and records how long it took.
The official score in the results file is not changed.

    python benchmark/run_published.py benchmark.cypherbench.rerun_timeouts
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from benchmark.cypherbench.common import engine_info, load_test
from benchmark.cypherbench.download import graph_path
from benchmark.cypherbench.loader import load_simplekg
from benchmark.cypherbench.metrics import execution_accuracy

IN = Path("benchmark/results/cypherbench_engine_parity.json")
OUT = Path("benchmark/results/cypherbench_engine_parity_timeouts.json")


def main() -> None:
    import gql_core

    res = json.loads(IN.read_text(encoding="utf-8"))
    test = {t["qid"]: t for t in load_test()}
    timeouts = [r for r in res["results"] if r["status"] == "timeout"]
    out = []
    for g in sorted({r["graph"] for r in timeouts}):
        graph, _ = load_simplekg(graph_path(g))
        for r in (x for x in timeouts if x["graph"] == g):
            t = time.perf_counter()
            rows = gql_core.run(test[r["qid"]]["gold_cypher"], graph)
            secs = time.perf_counter() - t
            ex = execution_accuracy(rows, test[r["qid"]]["answer_json"], test[r["qid"]]["gold_cypher"])
            out.append({"qid": r["qid"], "graph": g, "gold_cypher": r["gold_cypher"], "seconds": round(secs, 1),
                        "rows": len(rows), "execution_accuracy": ex})
            print(f"[{g}] {r['qid'][:8]} {secs:.1f}s EX={ex}", flush=True)
        del graph
    OUT.write_text(json.dumps({"engine": engine_info(), "timeout_in_full_run_seconds": res["timeout_seconds"],
                               "reruns_without_limit": out}, indent=2), encoding="utf-8")
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
