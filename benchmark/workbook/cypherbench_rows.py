"""Re-run the three CypherBench configurations' final queries and save the rows they return.

Run with the installed package, from the repository root:

    python benchmark/run_published.py benchmark/workbook/cypherbench_rows.py . cb_rows.json

The output (every returned row, up to 200 per query) feeds build_answers_workbook.py.
"""
import gc
import json
import sys

repo, out_path = sys.argv[1:3]
sys.path.insert(0, repo)
import os  # noqa: E402

os.chdir(repo)

from benchmark.cypherbench.common import load_test, run_with_timeout  # noqa: E402
from benchmark.cypherbench.download import graph_path  # noqa: E402
from benchmark.cypherbench.loader import load_simplekg  # noqa: E402
from benchmark.cypherbench.metrics import execution_accuracy  # noqa: E402

R = "benchmark/results/cypherbench_nl2cypher__gemini_gemini-2.5-flash"
configs = {name: {r["qid"]: r for r in json.load(open(f"{R}{suffix}.json", encoding="utf-8"))["results"]}
           for name, suffix in [("model", ""), ("corrected", "__corrected"), ("pipeline", "__pipeline")]}
gold = {x["qid"]: x for x in load_test()}
order = list(configs["model"])
graphs = []
for q in order:
    g = configs["model"][q]["graph"]
    if g not in graphs:
        graphs.append(g)

out = {}
for g in graphs:
    graph, _ = load_simplekg(graph_path(g))
    print(g, flush=True)
    for q in (x for x in order if configs["model"][x]["graph"] == g):
        out[q] = {}
        for name, recs in configs.items():
            r = recs[q]
            entry = {"query": r["pred_cypher"], "recorded_ex": r["execution_accuracy"]}
            try:
                rows = run_with_timeout(r["pred_cypher"], graph, 120)
                entry["rows"] = rows[:200]
                entry["n_rows"] = len(rows)
                entry["rerun_ex"] = execution_accuracy(rows, gold[q]["answer_json"], gold[q]["gold_cypher"])
            except Exception as exc:  # noqa: BLE001
                entry["error"] = f"{type(exc).__name__}: {exc}"[:300]
                entry["rerun_ex"] = 0.0
            out[q][name] = entry
        # The gold query on GQL-Core: if a prediction returns exactly these rows in this order,
        # it differs from Neo4j only where Neo4j's order is arbitrary (tied ORDER BY keys).
        try:
            out[q]["gold_on_engine"] = run_with_timeout(gold[q]["gold_cypher"], graph, 120)[:200]
        except Exception as exc:  # noqa: BLE001
            out[q]["gold_on_engine_error"] = f"{type(exc).__name__}: {exc}"[:300]
    del graph
    gc.collect()

json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, default=str)
print("saved", len(out), flush=True)
