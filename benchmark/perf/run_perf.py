"""GQL-Core Performance Benchmark v1: latency, stage timing, load time, memory and scaling.

Run it against the *installed* package with the launcher, from the repository root:

    python benchmark/run_published.py benchmark.perf.run_perf --all --sizes 10000 100000 500000

``--all`` runs every part in its own process (one per graph size, one per memory measurement,
one for the inference scaling series), so a part's memory never leaks into the next, then merges
the parts into ``benchmark/results/perf/perf_v1.json``. Parts can also be run one at a time with
``--size``, ``--memory`` or ``--inference-scaling``, and combined with ``--merge``.

Protocol, for every workload and system:

1. run once and compare the rows with the oracle; a wrong answer or an error is recorded and the
   system is not timed for that workload;
2. warm up (2 runs; 1 if a run takes over 2 s; none over 20 s);
3. time repeated runs until 200 samples or a time budget (default 5 s) is used, with at least 5
   samples (3 if one run takes over 20 s). p95 is reported only with at least 20 samples and p99
   only with at least 100; otherwise they are ``null``.

GQL-Core's openCypher path is also timed stage by stage (parse, validate, plan, execute), using
the same functions, in the same order, as ``gql_core.run``.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from benchmark.cypherbench.common import engine_info, git_commit
from benchmark.perf.baselines import build_networkx, build_sqlite
from benchmark.perf.generate import GENERATOR_VERSION, describe, generate, to_graph_dict
from benchmark.perf.workloads import WORKLOAD_VERSION, WORKLOADS, Ctx, gql_rows, normalize

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = Path("benchmark/results/perf")
SEED = 42
BIG_FACT_LIMIT = 50_000_000


# ── Measurement ─────────────────────────────────────────────────────────────────────────


def summarize(ns: list[int]) -> dict[str, Any]:
    xs = sorted(ns)
    n = len(xs)

    def q(f: float) -> float:
        return xs[min(n - 1, int(round(f * (n - 1))))] / 1e6

    return {
        "samples": n,
        "min_ms": xs[0] / 1e6, "p25_ms": q(0.25), "median_ms": statistics.median(xs) / 1e6,
        "p75_ms": q(0.75), "p90_ms": q(0.90),
        "p95_ms": q(0.95) if n >= 20 else None, "p99_ms": q(0.99) if n >= 100 else None,
        "max_ms": xs[-1] / 1e6, "mean_ms": statistics.fmean(xs) / 1e6,
        "stdev_ms": statistics.stdev(xs) / 1e6 if n > 1 else 0.0,
    }


def measure(fn: Callable[[], Any], first_ns: int, budget_s: float, max_n: int = 200) -> dict[str, Any]:
    warm = 0 if first_ns > 20e9 else 1 if first_ns > 2e9 else 2
    min_n = 3 if first_ns > 20e9 else 5
    for _ in range(warm):
        fn()
    samples: list[int] = []
    start = time.perf_counter()
    while len(samples) < max_n and (len(samples) < min_n or time.perf_counter() - start < budget_s):
        t = time.perf_counter_ns()
        fn()
        samples.append(time.perf_counter_ns() - t)
    return {"warmup_runs": warm, **summarize(samples)}


def timed(fn: Callable[[], Any]) -> tuple[Any, int]:
    t = time.perf_counter_ns()
    out = fn()
    return out, time.perf_counter_ns() - t


# ── GQL-Core entry points ───────────────────────────────────────────────────────────────


def cypher_stages(source: str, graph) -> tuple[list[dict], dict[str, int], str]:
    """``gql_core.run`` split into its stages, with the same functions in the same order."""
    from gql_core.query.executor import _is_pipeline_query, execute, execute_pipeline, plan_query
    from gql_core.query.parser import parse
    from gql_core.query.semantic import validate_query

    t0 = time.perf_counter_ns()
    query = parse(source)
    t1 = time.perf_counter_ns()
    validate_query(query, schema_path=None)
    t2 = time.perf_counter_ns()
    if _is_pipeline_query(query):
        rows, path, t3 = execute_pipeline(query, graph), "pipeline", t2
    else:
        try:
            p = plan_query(query, graph)
            t3 = time.perf_counter_ns()
            rows, path = execute(p, graph), "planner"
        except Exception:  # noqa: BLE001 - mirrors gql_core.run's fallback
            if not query.clauses:
                raise
            t3 = time.perf_counter_ns()
            rows, path = execute_pipeline(query, graph), "pipeline_fallback"
    t4 = time.perf_counter_ns()
    return rows, {"parse": t1 - t0, "validate": t2 - t1, "plan": t3 - t2, "execute": t4 - t3}, path


def plan_stages(make_plan: Callable[[], Any], graph) -> tuple[list[dict], dict[str, int]]:
    from gql_core import validate_logical_plan
    from gql_core.physical.engine import execute_physical_plan

    t0 = time.perf_counter_ns()
    root = make_plan()
    t1 = time.perf_counter_ns()
    report = validate_logical_plan(root, strict=True)
    if not report.is_valid:
        raise report.errors[0]
    t2 = time.perf_counter_ns()
    rows = execute_physical_plan(root, graph)
    t3 = time.perf_counter_ns()
    return rows, {"build": t1 - t0, "validate": t2 - t1, "execute": t3 - t2}


def stage_summary(fn: Callable[[], dict[str, int]], first_ns: int, budget_s: float) -> dict[str, Any]:
    samples: list[dict[str, int]] = []
    start = time.perf_counter()
    min_n = 3 if first_ns > 20e9 else 5
    while len(samples) < 100 and (len(samples) < min_n or time.perf_counter() - start < budget_s):
        samples.append(fn())
    return {k: round(statistics.median(s[k] for s in samples) / 1e6, 4) for k in samples[0]} | {"samples": len(samples)}


# ── One graph size ──────────────────────────────────────────────────────────────────────


def run_size(n: int, budget_s: float, only: set[str] | None) -> dict[str, Any]:
    import gql_core
    from gql_core import InferenceEngine, PropertyGraph, execute_plan, make_transitive_rule

    t = time.perf_counter()
    data = generate(n, SEED)
    gen_s = time.perf_counter() - t
    info = describe(data)
    ctx = Ctx(data)
    print(f"[{n}] generated {info['nodes']:,} nodes / {info['edges']:,} edges in {gen_s:.1f}s; params {ctx.params()}",
          flush=True)

    load: dict[str, Any] = {}
    gdict = to_graph_dict(data)
    g, ns = timed(lambda: PropertyGraph.from_dict(gdict))
    load["gql_core_from_dict_s"] = ns / 1e9
    del g, gdict
    gc.collect()

    def build_gql() -> PropertyGraph:
        from gql_core import Edge, Node
        graph = PropertyGraph()
        for lbl, recs in (("Person", data["persons"]), ("Company", data["companies"]), ("City", data["cities"])):
            for r in recs:
                graph.add_node(Node(id=r["id"], label=lbl, props=dict(r)))
        for i, (s, d) in enumerate(data["knows"]):
            graph.add_edge(Edge(id=f"k{i}", label="KNOWS", src=s, dst=d, props={}))
        for i, (s, d, since) in enumerate(data["works_at"]):
            graph.add_edge(Edge(id=f"w{i}", label="WORKS_AT", src=s, dst=d, props={"since": since}))
        for i, (s, d) in enumerate(data["lives_in"]):
            graph.add_edge(Edge(id=f"l{i}", label="LIVES_IN", src=s, dst=d, props={}))
        for i, (s, d) in enumerate(data["located_in"]):
            graph.add_edge(Edge(id=f"li{i}", label="LOCATED_IN", src=s, dst=d, props={}))
        for i, (s, d) in enumerate(data["subsidiary_of"]):
            graph.add_edge(Edge(id=f"s{i}", label="SUBSIDIARY_OF", src=s, dst=d, props={}))
        return graph

    graph, ns = timed(build_gql)
    load["gql_core_add_node_edge_s"] = ns / 1e9
    conn, ns = timed(lambda: build_sqlite(data))
    load["sqlite_memory_with_indexes_s"] = ns / 1e9
    nxg, ns = timed(lambda: build_networkx(data))
    load["networkx_s"] = ns / 1e9
    print(f"[{n}] load times {json.dumps({k: round(v, 2) for k, v in load.items()})}", flush=True)

    def systems(w) -> dict[str, Callable[[], list[tuple]]]:
        out: dict[str, Callable[[], list[tuple]]] = {}
        if w.inference:
            def infer(limit: int = BIG_FACT_LIMIT):
                eng = InferenceEngine(max_facts=limit)
                eng.add_rule(make_transitive_rule("SUBSIDIARY_OF"))
                return [(len(eng.infer(graph)[1]),)]
            out["gql_core"] = infer
        elif w.gql is not None:
            q = w.query_text(ctx)
            out["gql_core"] = lambda: gql_rows(gql_core.run(q, graph), w.cols)
        elif w.plan is not None:
            out["gql_core"] = lambda: gql_rows(execute_plan(w.plan(ctx), graph)["rows"], w.cols)
        out["python"] = lambda: w.oracle(ctx)
        if w.sqlite is not None and not w.needs_inferred_graph:
            sql = w.sql_text(ctx)
            out["sqlite"] = lambda: conn.execute(sql).fetchall()
        if w.networkx is not None:
            out["networkx"] = lambda: w.networkx(nxg, ctx)
        return out

    results: dict[str, Any] = {}
    todo = [w for w in WORKLOADS if (only is None or w.id in only)]
    base, derived = [w for w in todo if not w.needs_inferred_graph], [w for w in todo if w.needs_inferred_graph]
    materialize: dict[str, Any] | None = None

    for phase, batch in (("base", base), ("inferred", derived)):
        if phase == "inferred" and batch:
            eng = InferenceEngine(max_facts=BIG_FACT_LIMIT)
            eng.add_rule(make_transitive_rule("SUBSIDIARY_OF"))
            added, ns = timed(lambda: eng.materialize(graph))
            materialize = {"edges_added": added, "seconds": ns / 1e9}
            print(f"[{n}] materialized {added:,} inferred edges in {ns / 1e9:.1f}s", flush=True)
        for w in batch:
            gc.collect()
            expected = normalize(w.oracle(ctx), w.ordered)
            rec: dict[str, Any] = {"category": w.category, "description": w.description,
                                   "query": w.query_text(ctx), "sql": w.sql_text(ctx),
                                   "typed_plan": w.plan is not None, "rows_expected": len(expected),
                                   "expected": [list(r) for r in expected] if len(expected) <= 10 else None,
                                   "systems": {}}
            for name, fn in systems(w).items():
                try:
                    got, first = timed(fn)
                except Exception as exc:  # noqa: BLE001
                    rec["systems"][name] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}
                    continue
                got = normalize(got, w.ordered)
                if got != expected:
                    rec["systems"][name] = {"status": "wrong_result", "rows": len(got),
                                            "got_sample": [list(map(str, r)) for r in got[:5]],
                                            "expected_sample": [list(map(str, r)) for r in expected[:5]]}
                    continue
                rec["systems"][name] = {"status": "ok", "first_run_ms": first / 1e6,
                                        **measure(fn, first, budget_s)}
            gq = rec["systems"].get("gql_core", {})
            if gq.get("status") == "ok" and not w.inference:
                first_ns = int(gq["first_run_ms"] * 1e6)
                if w.gql is not None:
                    q = w.query_text(ctx)
                    _, _, path = cypher_stages(q, graph)
                    rec["gql_core_stages"] = {"path": path, **stage_summary(lambda: cypher_stages(q, graph)[1],
                                                                             first_ns, budget_s / 2)}
                else:
                    rec["gql_core_stages"] = {"path": "typed_plan", **stage_summary(
                        lambda: plan_stages(lambda: w.plan(ctx), graph)[1], first_ns, budget_s / 2)}
            if w.inference:
                eng = InferenceEngine()  # the default max_facts=250,000
                eng.add_rule(make_transitive_rule("SUBSIDIARY_OF"))
                rec["default_engine_derived"] = len(eng.infer(graph)[1])
            results[w.id] = rec
            line = "  ".join(f"{s}={v.get('median_ms', v['status']) if v['status'] == 'ok' else v['status']}"
                             for s, v in rec["systems"].items())
            print(f"[{n}] {w.id:<28} rows={len(expected):<7} {line}", flush=True)

    return {"size": n, "graph": info, "generate_seconds": gen_s, "load": load,
            "materialize_inferred": materialize, "workloads": results}


# ── Memory: one system per process ──────────────────────────────────────────────────────


def run_memory(n: int, system: str) -> dict[str, Any]:
    import psutil

    data = generate(n, SEED)
    gc.collect()
    proc = psutil.Process()
    before = proc.memory_info().rss
    if system == "gql_core":
        from gql_core import PropertyGraph
        gdict = to_graph_dict(data)
        gc.collect()
        before = proc.memory_info().rss
        obj = PropertyGraph.from_dict(gdict)
        del gdict  # the graph keeps its own node and edge objects
    elif system == "sqlite":
        obj = build_sqlite(data)
    elif system == "networkx":
        obj = build_networkx(data)
    else:
        raise SystemExit(f"unknown system {system}")
    gc.collect()
    after = proc.memory_info().rss
    info = describe(data)
    elems = info["nodes"] + info["edges"]
    _ = obj
    return {"size": n, "system": system, "nodes": info["nodes"], "edges": info["edges"],
            "rss_delta_mb": (after - before) / 2**20, "bytes_per_node_or_edge": (after - before) / elems,
            "peak_working_set_mb": getattr(proc.memory_info(), "peak_wset", 0) / 2**20 or None}


# ── Inference scaling on isolated hierarchies ───────────────────────────────────────────


def run_inference_scaling(sizes: list[int], budget_s: float) -> list[dict[str, Any]]:
    from gql_core import Edge, InferenceEngine, Node, PropertyGraph, make_transitive_rule

    out = []
    for k in sizes:
        graph = PropertyGraph()
        for i in range(k):
            graph.add_node(Node(id=f"c{i}", label="Company", props={}))
        edges = [(f"c{i}", f"c{(i - 1) // 4}") for i in range(1, k) if i % 10]
        for j, (s, d) in enumerate(edges):
            graph.add_edge(Edge(id=f"s{j}", label="SUBSIDIARY_OF", src=s, dst=d, props={}))
        parent = dict(edges)

        def depth(c: str) -> int:
            d = 0
            while c in parent:
                c, d = parent[c], d + 1
            return d

        expected = sum(max(0, depth(f"c{i}") - 1) for i in range(k))

        def infer():
            eng = InferenceEngine(max_facts=BIG_FACT_LIMIT)
            eng.add_rule(make_transitive_rule("SUBSIDIARY_OF"))
            return len(eng.infer(graph)[1])

        got, first = timed(infer)
        rec = {"companies": k, "asserted_edges": len(edges), "derived_expected": expected, "derived": got,
               "correct": got == expected}
        if got == expected:
            rec.update(measure(infer, first, budget_s, max_n=50))
        print(f"[inference] {k:>7} companies: derived {got:,} (expected {expected:,}) "
              f"median {rec.get('median_ms', float('nan')):.1f} ms", flush=True)
        out.append(rec)
    return out


# ── Environment and orchestration ───────────────────────────────────────────────────────


def environment() -> dict[str, Any]:
    import sqlite3

    import psutil
    cpu = platform.processor()
    if sys.platform == "win32":
        try:
            cpu = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"],
                                 capture_output=True, text=True, timeout=30).stdout.strip() or cpu
        except Exception:  # noqa: BLE001
            pass
    try:
        import networkx
        nx_version = networkx.__version__
    except ImportError:
        nx_version = None
    return {
        "engine": engine_info(), "git_commit": git_commit(),
        "python": sys.version.split()[0], "implementation": platform.python_implementation(),
        "os": f"{platform.system()} {platform.release()} ({platform.version()})", "machine": platform.machine(),
        "cpu": cpu, "logical_cpus": os.cpu_count(), "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "sqlite": sqlite3.sqlite_version, "networkx": nx_version,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
    }


def spawn(args: list[str]) -> None:
    cmd = [sys.executable, str(REPO / "benchmark" / "run_published.py"), "benchmark.perf.run_perf", *args]
    print("$", " ".join(args), flush=True)
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--all", action="store_true", help="run every part in its own process, then merge")
    ap.add_argument("--sizes", type=int, nargs="+", default=[10_000, 100_000, 500_000])
    ap.add_argument("--size", type=int, help="run the workloads on one graph size")
    ap.add_argument("--memory", type=int, help="measure the memory of one system on one graph size")
    ap.add_argument("--system", default="gql_core", choices=["gql_core", "sqlite", "networkx"])
    ap.add_argument("--inference-scaling", type=int, nargs="*", help="hierarchy sizes for the inference series")
    ap.add_argument("--merge", action="store_true", help="combine the part files in --out-dir")
    ap.add_argument("--only", nargs="+", help="run only these workload ids")
    ap.add_argument("--budget", type=float, default=5.0, help="timing budget per workload and system (s)")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    def save(name: str, obj: Any) -> None:
        path = args.out_dir / name
        path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"saved {path}", flush=True)

    if args.all:
        for n in args.sizes:
            for s in ("gql_core", "sqlite", "networkx"):
                spawn(["--memory", str(n), "--system", s, "--out-dir", str(args.out_dir)])
        spawn(["--inference-scaling", "250", "500", "1000", "2000", "--out-dir", str(args.out_dir)])
        for n in args.sizes:
            spawn(["--size", str(n), "--budget", str(args.budget), "--out-dir", str(args.out_dir)])
        spawn(["--merge", "--out-dir", str(args.out_dir)])
        return

    if args.size:
        save(f"size_{args.size}.json", {"environment": environment(), "workload_version": WORKLOAD_VERSION,
                                        "generator_version": GENERATOR_VERSION, "seed": SEED,
                                        "budget_seconds": args.budget,
                                        **run_size(args.size, args.budget, set(args.only) if args.only else None)})
    elif args.memory:
        save(f"memory_{args.memory}_{args.system}.json", {"environment": environment(),
                                                          **run_memory(args.memory, args.system)})
    elif args.inference_scaling is not None:
        save("inference_scaling.json", {"environment": environment(), "series": run_inference_scaling(
            args.inference_scaling or [1000, 4000, 16000, 64000], args.budget)})
    elif args.merge:
        parts = sorted(p for p in args.out_dir.glob("*.json") if p.name != "perf_v1.json")
        loaded = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in parts}
        engines = {json.dumps(v["environment"]["engine"], sort_keys=True) for v in loaded.values()}
        if len(engines) != 1:
            raise SystemExit("the part files were produced by different engines")
        env = next(iter(loaded.values()))["environment"]
        merged = {
            "benchmark": "GQL-Core Performance Benchmark v1", "workload_version": WORKLOAD_VERSION,
            "generator_version": GENERATOR_VERSION, "seed": SEED, "environment": env,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sizes": [{k: v for k, v in loaded[s].items() if k != "environment"}
                      for s in sorted((s for s in loaded if s.startswith("size_")), key=lambda s: int(s[5:]))],
            "memory": [{k: v for k, v in loaded[s].items() if k != "environment"}
                       for s in sorted(s for s in loaded if s.startswith("memory_"))],
            "inference_scaling": loaded.get("inference_scaling", {}).get("series"),
        }
        save("perf_v1.json", merged)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
