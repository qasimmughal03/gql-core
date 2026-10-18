"""LDBC SNB Interactive v1 Benchmark Runner for GQL-Core.

Executes supported SNB queries strictly through GQL-Core's public API, verifies
exact answer correctness against the relational SQLite Oracle, records end-to-end
and separate phase latencies, and outputs a complete reproducible report.
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
from benchmark.snb.loader import load_snb_dataset
from benchmark.snb.oracle import SNBAnswerOracle

DEFAULT_OUTPUT_JSON = Path("benchmark/results/snb_interactive_results.json")

# Benchmark parameter sets (using official LDBC SNB parameters)
TEST_WORKLOAD = [
    {
        "query_id": "IS1",
        "param_id": "IS1_p1",
        "params": {"personId": 4398046511192},
        "query": (
            "MATCH (n:Person {id: 4398046511192})-[:IS_LOCATED_IN]->(p:City) "
            "RETURN n.firstName AS firstName, n.lastName AS lastName, n.birthday AS birthday, "
            "n.locationIP AS locationIP, n.browserUsed AS browserUsed, p.id AS cityId, "
            "n.gender AS gender, n.creationDate AS creationDate"
        ),
    },
    {
        "query_id": "IS1",
        "param_id": "IS1_p2",
        "params": {"personId": 8796093022220},
        "query": (
            "MATCH (n:Person {id: 8796093022220})-[:IS_LOCATED_IN]->(p:City) "
            "RETURN n.firstName AS firstName, n.lastName AS lastName, n.birthday AS birthday, "
            "n.locationIP AS locationIP, n.browserUsed AS browserUsed, p.id AS cityId, "
            "n.gender AS gender, n.creationDate AS creationDate"
        ),
    },
    {
        "query_id": "IS3",
        "param_id": "IS3_p1",
        "params": {"personId": 4398046511192},
        "query": (
            "MATCH (n:Person {id: 4398046511192})-[r:KNOWS]-(friend:Person) "
            "RETURN friend.id AS personId, friend.firstName AS firstName, "
            "friend.lastName AS lastName, r.creationDate AS friendshipCreationDate "
            "ORDER BY friendshipCreationDate DESC, personId ASC"
        ),
    },
    {
        "query_id": "IS3",
        "param_id": "IS3_p2",
        "params": {"personId": 8796093022220},
        "query": (
            "MATCH (n:Person {id: 8796093022220})-[r:KNOWS]-(friend:Person) "
            "RETURN friend.id AS personId, friend.firstName AS firstName, "
            "friend.lastName AS lastName, r.creationDate AS friendshipCreationDate "
            "ORDER BY friendshipCreationDate DESC, personId ASC"
        ),
    },
    {
        "query_id": "IS5",
        "param_id": "IS5_p1",
        "params": {"messageId": 206158431836},
        "query": (
            "MATCH (m:Post {id: 206158431836})-[:HAS_CREATOR]->(p:Person) "
            "RETURN p.id AS personId, p.firstName AS firstName, p.lastName AS lastName"
        ),
    },
    {
        "query_id": "IS5",
        "param_id": "IS5_p2",
        "params": {"messageId": 206158431840},
        "query": (
            "MATCH (m:Post {id: 206158431840})-[:HAS_CREATOR]->(p:Person) "
            "RETURN p.id AS personId, p.firstName AS firstName, p.lastName AS lastName"
        ),
    },
    {
        "query_id": "IC2",
        "param_id": "IC2_p1",
        "params": {"personId": 10995116278009, "maxDate": 1287187200000},
        "query": (
            "MATCH (:Person {id: 10995116278009})-[:KNOWS]-(friend:Person)<-[:HAS_CREATOR]-(message:Post) "
            "WHERE message.creationDate <= 1287187200000 "
            "RETURN friend.id AS personId, friend.firstName AS personFirstName, "
            "friend.lastName AS personLastName, message.id AS postOrCommentId, "
            "message.content AS postOrCommentContent, message.creationDate AS postOrCommentCreationDate "
            "ORDER BY postOrCommentCreationDate DESC, postOrCommentId ASC "
            "LIMIT 20"
        ),
    },
    {
        "query_id": "IC8",
        "param_id": "IC8_p1",
        "params": {"personId": 143},
        "query": (
            "MATCH (start:Person {id: 143})<-[:HAS_CREATOR]-(post:Post)<-[:REPLY_OF]-(comment:Comment)-[:HAS_CREATOR]->(person:Person) "
            "RETURN person.id AS personId, person.firstName AS personFirstName, "
            "person.lastName AS personLastName, comment.creationDate AS commentCreationDate, "
            "comment.id AS commentId, comment.content AS commentContent "
            "ORDER BY commentCreationDate DESC, commentId ASC "
            "LIMIT 20"
        ),
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
    output_json: Path | str = DEFAULT_OUTPUT_JSON,
    warmup_runs: int = 3,
    sample_runs: int = 10,
) -> dict[str, Any]:
    output_json = Path(output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    print("============================================================")
    print("  LDBC SNB Interactive v1 Read-Only Benchmark for GQL-Core")
    print("  Disclaimer: Unaudited read-only performance study using LDBC SNB Interactive v1 queries")
    print("============================================================")

    # 1. Load Dataset
    print("  Loading official LDBC SNB initial snapshot dataset...")
    graph, load_stats = load_snb_dataset()
    print(f"  Loaded {load_stats['nodes']} nodes and {load_stats['edges']} edges in {load_stats['load_time_seconds']}s")
    print(f"  Peak memory RSS delta: {load_stats['peak_memory_rss_mb']} MB")
    print("------------------------------------------------------------")

    # 2. Initialize Answer Oracle
    print("  Initializing relational SQLite Answer Oracle...")
    oracle = SNBAnswerOracle()
    print("  Answer Oracle initialized successfully.")
    print("------------------------------------------------------------")

    # 3. Execute Workload
    results = []
    all_passed_correctness = True

    for item in TEST_WORKLOAD:
        qid = item["query_id"]
        pid = item["param_id"]
        q_str = item["query"]
        params = item["params"]

        print(f"  Running {qid} [{pid}]...", end="", flush=True)

        # Compute Oracle Answer
        if qid == "IS1":
            expected = oracle.execute_is1(params["personId"])
        elif qid == "IS3":
            expected = oracle.execute_is3(params["personId"])
        elif qid == "IS5":
            expected = oracle.execute_is5(params["messageId"])
        elif qid == "IC2":
            expected = oracle.execute_ic2(params["personId"], params["maxDate"])
        elif qid == "IC8":
            expected = oracle.execute_ic8(params["personId"])
        else:
            expected = []

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

        # Measure separate phase timings (average over 5 runs)
        parse_times: list[float] = []
        plan_times: list[float] = []
        exec_times: list[float] = []

        for _ in range(5):
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

        sorted_lats = sorted(latencies_ms)
        median_lat = statistics.median(sorted_lats)
        mean_lat = statistics.mean(sorted_lats)
        std_lat = statistics.stdev(sorted_lats) if len(sorted_lats) > 1 else 0.0
        p95_lat = _percentile(sorted_lats, 0.95)

        avg_parse = statistics.mean(parse_times)
        avg_plan = statistics.mean(plan_times)
        avg_exec = statistics.mean(exec_times)

        print(f" {status_str} | rows={len(actual_rows)} | med={median_lat:.3f}ms | p95={p95_lat:.3f}ms")

        results.append({
            "query_id": qid,
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
            "scale_factor": "SF0.1 / initial snapshot (34,735 nodes, 71,667 edges)",
            "all_verified_correct": all_passed_correctness,
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
    print(f"  All tested queries verified exact match against Oracle: {all_passed_correctness}")
    print("============================================================")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run LDBC SNB Interactive v1 Benchmark")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_JSON), help="Output JSON path")
    parser.add_argument("--warmup", type=int, default=3, help="Warm-up runs")
    parser.add_argument("--samples", type=int, default=10, help="Sample measured runs")
    args = parser.parse_args()

    data = run_benchmark(output_json=args.output, warmup_runs=args.warmup, sample_runs=args.samples)
    if not data["metadata"]["all_verified_correct"]:
        sys.exit(1)
    sys.exit(0)
