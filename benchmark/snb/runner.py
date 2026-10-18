"""LDBC SNB Interactive v1 Benchmark Runner for GQL-Core.

Executes official read operations strictly through GQL-Core's public API, verifies
exact answer correctness against the relational SQLite Oracle, records end-to-end
and separate phase latencies, and outputs a complete reproducible report.
Distinguishes official operations (Categories A & B) from simplified adaptations (Category C).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil

import gql_core
from gql_core import parse, plan
from gql_core.query.executor import execute
from benchmark.snb.inventory import SNB_READ_QUERY_INVENTORY, get_inventory_summary
from benchmark.snb.loader import load_snb_dataset, DATASET_CATALOG
from benchmark.snb.oracle import SNBAnswerOracle

DEFAULT_OUTPUT_JSON = Path("benchmark/results/snb_interactive_results.json")

# Official SF0.1 Workload
# Tested on official SF0.1 dataset (327,588 nodes, 1,477,965 edges)
WORKLOAD_SF01 = [
    # ── Category A: Exact Supported Official Operation ──────────
    {
        "query_id": "IS1",
        "semantic_category": "A",
        "category_description": "Exact supported official operation",
        "parameter_id": "IS1_sf01_p1",
        "params": {"personId": 2199023256816},
        "query": (
            "MATCH (n:Person {id: 2199023256816})-[:IS_LOCATED_IN]->(p:City) "
            "RETURN n.firstName AS firstName, n.lastName AS lastName, n.birthday AS birthday, "
            "n.locationIP AS locationIP, n.browserUsed AS browserUsed, p.id AS cityId, "
            "n.gender AS gender, n.creationDate AS creationDate"
        ),
    },
    {
        "query_id": "IS1",
        "semantic_category": "A",
        "category_description": "Exact supported official operation",
        "parameter_id": "IS1_sf01_p2",
        "params": {"personId": 6597069767242},
        "query": (
            "MATCH (n:Person {id: 6597069767242})-[:IS_LOCATED_IN]->(p:City) "
            "RETURN n.firstName AS firstName, n.lastName AS lastName, n.birthday AS birthday, "
            "n.locationIP AS locationIP, n.browserUsed AS browserUsed, p.id AS cityId, "
            "n.gender AS gender, n.creationDate AS creationDate"
        ),
    },

    # ── Category B: Semantically Equivalent Translation ──────────
    {
        "query_id": "IS3",
        "semantic_category": "B",
        "category_description": "Semantically equivalent translation",
        "parameter_id": "IS3_sf01_p1",
        "params": {"personId": 2199023256816},
        "query": (
            "MATCH (n:Person {id: 2199023256816})-[r:KNOWS]-(friend:Person) "
            "RETURN friend.id AS personId, friend.firstName AS firstName, "
            "friend.lastName AS lastName, r.creationDate AS friendshipCreationDate "
            "ORDER BY friendshipCreationDate DESC, personId ASC"
        ),
    },
    {
        "query_id": "IS3",
        "semantic_category": "B",
        "category_description": "Semantically equivalent translation",
        "parameter_id": "IS3_sf01_p2",
        "params": {"personId": 6597069767242},
        "query": (
            "MATCH (n:Person {id: 6597069767242})-[r:KNOWS]-(friend:Person) "
            "RETURN friend.id AS personId, friend.firstName AS firstName, "
            "friend.lastName AS lastName, r.creationDate AS friendshipCreationDate "
            "ORDER BY friendshipCreationDate DESC, personId ASC"
        ),
    },

    # ── Category C: Simplified / Partially Equivalent Adaptations ─
    {
        "query_id": "IS5",
        "semantic_category": "C",
        "category_description": "Simplified or partially equivalent adaptation (Post only)",
        "parameter_id": "IS5_sf01_p1",
        "params": {"messageId": 206158430209},
        "query": (
            "MATCH (m:Post {id: 206158430209})-[:HAS_CREATOR]->(p:Person) "
            "RETURN p.id AS personId, p.firstName AS firstName, p.lastName AS lastName"
        ),
        "notes": "Adapted from Message to Post. Only matches post authors; does not match comments.",
    },
    {
        "query_id": "IC2",
        "semantic_category": "C",
        "category_description": "Simplified or partially equivalent adaptation (Post only)",
        "parameter_id": "IC2_sf01_p1",
        "params": {"personId": 2199023256816, "maxDate": 1354320000000},
        "query": (
            "MATCH (:Person {id: 2199023256816})-[:KNOWS]-(friend:Person)<-[:HAS_CREATOR]-(message:Post) "
            "WHERE message.creationDate <= 1354320000000 "
            "RETURN friend.id AS personId, friend.firstName AS personFirstName, "
            "friend.lastName AS personLastName, message.id AS postOrCommentId, "
            "message.content AS postOrCommentContent, message.creationDate AS postOrCommentCreationDate "
            "ORDER BY postOrCommentCreationDate DESC, postOrCommentId ASC "
            "LIMIT 20"
        ),
        "notes": "Adapted from Message to Post, omitting comments and coalesce(content, imageFile).",
    },
    {
        "query_id": "IC8",
        "semantic_category": "C",
        "category_description": "Simplified or partially equivalent adaptation (Post replies only)",
        "parameter_id": "IC8_sf01_p1",
        "params": {"personId": 2199023256816},
        "query": (
            "MATCH (start:Person {id: 2199023256816})<-[:HAS_CREATOR]-(post:Post)<-[:REPLY_OF]-(comment:Comment)-[:HAS_CREATOR]->(person:Person) "
            "RETURN person.id AS personId, person.firstName AS personFirstName, "
            "person.lastName AS personLastName, comment.creationDate AS commentCreationDate, "
            "comment.id AS commentId, comment.content AS commentContent "
            "ORDER BY commentCreationDate DESC, commentId ASC "
            "LIMIT 20"
        ),
        "notes": "Adapted from Message to Post. Only matches replies to Posts, not threaded replies to Comments.",
    },
]


def _get_git_commit() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "unknown"


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    k = (len(data) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data[int(k)]
    return data[int(f)] * (c - k) + data[int(c)] * (k - f)


def run_benchmark(
    dataset: str = "official_sf01",
    output_json: Path | str = DEFAULT_OUTPUT_JSON,
    warmup_runs: int = 2,
    sample_runs: int = 10,
) -> dict[str, Any]:
    output_json = Path(output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    print("============================================================")
    print("  LDBC SNB Interactive v1 Read-Only Benchmark for GQL-Core")
    print("  Disclaimer: Unaudited read-only performance study using LDBC SNB Interactive v1 queries")
    print("============================================================")

    # 1. Load Dataset
    print(f"  Loading dataset [{dataset}]...")
    graph, load_stats = load_snb_dataset(dataset)
    print(f"  Loaded {load_stats['nodes']} nodes and {load_stats['edges']} edges in {load_stats['load_time_seconds']}s")
    print(f"  Peak memory RSS delta: {load_stats['peak_memory_rss_mb']} MB")
    print("------------------------------------------------------------")

    # 2. Initialize Answer Oracle
    print("  Initializing relational SQLite Answer Oracle...")
    oracle = SNBAnswerOracle(dataset)
    print("  Answer Oracle initialized successfully.")
    print("------------------------------------------------------------")

    # 3. Execute Workload
    results = []
    official_passes = 0
    official_evals = 0
    all_passed_correctness = True

    for item in WORKLOAD_SF01:
        qid = item["query_id"]
        cat = item["semantic_category"]
        pid = item["parameter_id"]
        q_str = item["query"]
        params = item["params"]

        print(f"  Running {qid} [Cat {cat} | {pid}]...", end="", flush=True)

        # Compute Oracle Answer & Oracle latency
        if qid == "IS1":
            expected, ora_lat = oracle.execute_is1(params["personId"])
        elif qid == "IS3":
            expected, ora_lat = oracle.execute_is3(params["personId"])
        elif qid == "IS5":
            expected, ora_lat = oracle.execute_is5_adapted_post(params["messageId"])
        elif qid == "IC2":
            expected, ora_lat = oracle.execute_ic2_adapted_post(params["personId"], params["maxDate"])
        elif qid == "IC8":
            expected, ora_lat = oracle.execute_ic8_adapted_post(params["personId"])
        else:
            expected, ora_lat = [], 0.0

        # Warm-up runs
        for _ in range(warmup_runs):
            gql_core.run(q_str, graph)

        # Measured runs
        latencies_ms: list[float] = []
        actual_rows: list[dict[str, Any]] = []

        for _ in range(sample_runs):
            t0 = time.perf_counter()
            actual_rows = gql_core.run(q_str, graph)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(elapsed_ms)

        # Measure separate phase timings (average over 3 runs)
        parse_times: list[float] = []
        plan_times: list[float] = []
        exec_times: list[float] = []

        for _ in range(3):
            t_p0 = time.perf_counter()
            ast = parse(q_str)
            t_p1 = time.perf_counter()
            q_plan = plan(ast)
            t_p2 = time.perf_counter()
            execute(q_plan, graph)
            t_p3 = time.perf_counter()

            parse_times.append((t_p1 - t_p0) * 1000.0)
            plan_times.append((t_p2 - t_p1) * 1000.0)
            exec_times.append((t_p3 - t_p2) * 1000.0)

        # Check correctness against Oracle
        is_correct = (actual_rows == expected)
        if not is_correct:
            all_passed_correctness = False
            status_str = "MISMATCH"
        else:
            status_str = "VERIFIED_EXACT_MATCH"

        if cat in ("A", "B"):
            official_evals += 1
            if is_correct:
                official_passes += 1

        sorted_lats = sorted(latencies_ms)
        median_lat = statistics.median(sorted_lats)
        mean_lat = statistics.mean(sorted_lats)
        std_lat = statistics.stdev(sorted_lats) if len(sorted_lats) > 1 else 0.0
        p95_lat = _percentile(sorted_lats, 0.95)

        avg_parse = statistics.mean(parse_times)
        avg_plan = statistics.mean(plan_times)
        avg_exec = statistics.mean(exec_times)

        print(f" {status_str} | rows={len(actual_rows)} | med={median_lat:.3f}ms | p95={p95_lat:.3f}ms | sqlite_med={ora_lat:.3f}ms")

        results.append({
            "query_id": qid,
            "semantic_category": cat,
            "category_description": item["category_description"],
            "parameter_id": pid,
            "parameters": params,
            "query_string": q_str,
            "correctness_status": status_str,
            "result_row_count": len(actual_rows),
            "expected_row_count": len(expected),
            "sample_count": sample_runs,
            "warmup_count": warmup_runs,
            "latency_ms": {
                "median": round(median_lat, 4),
                "mean": round(mean_lat, 4),
                "stddev": round(std_lat, 4),
                "min": round(sorted_lats[0], 4),
                "max": round(sorted_lats[-1], 4),
                "p95": round(p95_lat, 4),
                "samples": [round(x, 4) for x in latencies_ms],
            },
            "phase_timings_ms": {
                "parse_mean": round(avg_parse, 4),
                "plan_mean": round(avg_plan, 4),
                "execution_mean": round(avg_exec, 4),
            },
            "sqlite_baseline_ms": round(ora_lat, 4),
            "notes": item.get("notes"),
        })

    # System and environment specifications
    vm = psutil.virtual_memory()
    system_metadata = {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "processor": platform.processor(),
        "cpu_count_logical": os.cpu_count(),
        "total_ram_gb": round(vm.total / (1024**3), 2),
        "available_ram_gb": round(vm.available / (1024**3), 2),
        "python_version": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "package_name": "gql-core",
        "package_version": getattr(gql_core, "__version__", "0.2.0"),
        "package_location": str(Path(gql_core.__file__).parent),
        "git_commit": _get_git_commit(),
        "workload_disclaimer": "Unaudited read-only performance study using LDBC SNB Interactive v1 queries",
    }

    report = {
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "benchmark_suite": "LDBC SNB Interactive v1 Read-Only",
            "dataset": {k: str(v) if isinstance(v, Path) else v for k, v in DATASET_CATALOG.get(dataset, {"dataset_name": dataset}).items()},
            "all_verified_correct": all_passed_correctness,
            "official_evaluation_summary": {
                "official_operations_evaluated": official_evals,
                "official_operations_passed": official_passes,
                "official_pass_rate_pct": round((official_passes / official_evals * 100.0), 2) if official_evals else 0.0,
                "category_c_studies_evaluated": len(results) - official_evals,
                "category_c_status": "Reported separately as simplified adaptations; NOT counted as official passes.",
            },
            "system": system_metadata,
            "dataset_loading": load_stats,
            "inventory_summary": get_inventory_summary(),
        },
        "query_results": results,
    }

    with open(output_json, "w", encoding="utf-8") as fp:
        json.dump(report, fp, indent=2)

    print("------------------------------------------------------------")
    print(f"  Benchmark complete. Wrote full report to: {output_json}")
    print(f"  Official operations (Cat A & B): {official_passes}/{official_evals} passed exact match.")
    print(f"  All tested queries verified exact match against Oracle: {all_passed_correctness}")
    print("============================================================")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run LDBC SNB Interactive v1 Benchmark")
    parser.add_argument("--dataset", default="official_sf01", choices=["official_sf01", "reference_vanilla"], help="Dataset to benchmark")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_JSON), help="Output JSON path")
    parser.add_argument("--warmup", type=int, default=2, help="Warm-up runs")
    parser.add_argument("--samples", type=int, default=5, help="Sample measured runs")
    args = parser.parse_args()

    data = run_benchmark(
        dataset=args.dataset,
        output_json=args.output,
        warmup_runs=args.warmup,
        sample_runs=args.samples,
    )
    if not data["metadata"]["all_verified_correct"]:
        sys.exit(1)
    sys.exit(0)
