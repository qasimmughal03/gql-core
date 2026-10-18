"""openCypher TCK Compatibility Test Runner.

Inventories upstream openCypher TCK corpus, classifies scenarios against the
declared GQL-Core v0.2.0 language subset, executes supported scenarios via the
installed public API, and writes an evidence-based report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from benchmark.tck.gherkin_parser import parse_feature_file, TCKScenario
from benchmark.tck.tck_adapter import run_scenario

DEFAULT_TCK_DIR = Path("benchmark/cache/openCypher/tck/features")
DEFAULT_OUTPUT_JSON = Path("benchmark/results/tck_compatibility_results.json")


def run_tck_suite(
    tck_dir: Path | str = DEFAULT_TCK_DIR,
    output_json: Path | str = DEFAULT_OUTPUT_JSON,
    feature_filter: str | None = None,
    max_scenarios: int | None = None,
) -> dict[str, Any]:
    tck_dir = Path(tck_dir)
    output_json = Path(output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    if not tck_dir.exists():
        raise FileNotFoundError(f"openCypher TCK directory not found at {tck_dir}. Run git clone first.")

    feature_files = sorted(tck_dir.rglob("*.feature"))
    if feature_filter:
        feature_files = [f for f in feature_files if feature_filter.lower() in f.as_posix().lower()]

    print(f"============================================================")
    print(f"  openCypher TCK Compatibility Suite (pinned to 2024.3)")
    print(f"============================================================")
    print(f"  Found {len(feature_files)} feature files in {tck_dir}")

    all_scenarios: list[TCKScenario] = []
    for ff in feature_files:
        try:
            scs = parse_feature_file(ff)
            all_scenarios.extend(scs)
        except Exception as e:
            print(f"  [WARN] Failed to parse feature file {ff}: {e}")

    if max_scenarios:
        all_scenarios = all_scenarios[:max_scenarios]

    print(f"  Total Scenarios Inventoried: {len(all_scenarios)}")
    print(f"------------------------------------------------------------")

    results = []
    status_counts = Counter()
    unsupported_reasons = Counter()
    failure_details = []
    by_category = defaultdict(lambda: Counter())

    # Also track diagnostic results (relaxed column matching for unaliased expressions)
    diag_status_counts = Counter()
    diag_failures = []

    start_time = time.perf_counter()

    for idx, sc in enumerate(all_scenarios):
        # 1. Strict mode execution (exact openCypher column names required)
        res = run_scenario(sc, relaxed_columns=False)
        results.append(res)
        st = res["status"]
        status_counts[st] += 1

        rel_cat = Path(sc.file_path).parent.relative_to(tck_dir).as_posix().split("/")[0]
        by_category[rel_cat][st] += 1

        if st == "unsupported":
            unsupported_reasons[res.get("reason", "UNKNOWN")] += 1
            diag_status_counts["unsupported"] += 1
        elif st == "failed":
            failure_details.append({
                "scenario_id": sc.scenario_id,
                "name": sc.name,
                "file": str(Path(sc.file_path).name),
                "query": sc.query,
                "reason": res.get("reason"),
            })
            # Check if this failure passes in diagnostic mode (unaliased column naming differences)
            diag_res = run_scenario(sc, relaxed_columns=True)
            diag_st = diag_res["status"]
            diag_status_counts[diag_st] += 1
            if diag_st == "failed":
                diag_failures.append({
                    "scenario_id": sc.scenario_id,
                    "name": sc.name,
                    "file": str(Path(sc.file_path).name),
                    "query": sc.query,
                    "reason": diag_res.get("reason"),
                })
        else:
            diag_status_counts[st] += 1

    total_time = time.perf_counter() - start_time

    total = len(all_scenarios)
    unsupported_count = status_counts["unsupported"]
    claimed_count = total - unsupported_count
    passed_count = status_counts["passed"]
    failed_count = status_counts["failed"]
    blocked_count = status_counts["blocked"]

    pass_rate_claimed = (passed_count / claimed_count * 100.0) if claimed_count > 0 else 0.0
    overall_coverage = (passed_count / total * 100.0) if total > 0 else 0.0

    diag_passed = diag_status_counts["passed"]
    diag_failed = diag_status_counts["failed"]
    diag_pass_rate = (diag_passed / claimed_count * 100.0) if claimed_count > 0 else 0.0

    print(f"  Execution complete in {total_time:.2f}s")
    print(f"")
    print(f"  STRICT MODE (Exact openCypher Column Names):")
    print(f"  Total Scenarios Inventoried:       {total}")
    print(f"  Classified as Unsupported:          {unsupported_count} ({unsupported_count/total*100:.1f}%)")
    print(f"  In Claimed Language Subset:         {claimed_count}")
    print(f"  Passed within Claimed Subset:       {passed_count} / {claimed_count} ({pass_rate_claimed:.1f}%)")
    print(f"  Failed within Claimed Subset:       {failed_count} / {claimed_count}")
    print(f"  Blocked Scenarios:                  {blocked_count}")
    print(f"  Overall openCypher Suite Coverage:  {overall_coverage:.1f}% ({passed_count}/{total})")
    print(f"------------------------------------------------------------")
    print(f"  DIAGNOSTIC MODE (Relaxed Column Aliasing for Expressions):")
    print(f"  Passed within Claimed Subset:       {diag_passed} / {claimed_count} ({diag_pass_rate:.1f}%)")
    print(f"  Failed within Claimed Subset:       {diag_failed} / {claimed_count}")
    print(f"  Naming-drift Scenarios:             {diag_passed - passed_count} (pass in diagnostic mode)")
    print(f"------------------------------------------------------------")
    print(f"  Breakdown by Category (Strict):")
    for cat, counts in sorted(by_category.items()):
        c_tot = sum(counts.values())
        c_pass = counts["passed"]
        c_unsupp = counts["unsupported"]
        c_fail = counts["failed"]
        print(f"    {cat:<25}: total={c_tot:<4} passed={c_pass:<4} unsupp={c_unsupp:<4} fail={c_fail:<4}")

    print(f"------------------------------------------------------------")
    print(f"  Top Unsupported Feature Drivers:")
    for reason, count in unsupported_reasons.most_common(8):
        print(f"    {reason:<35}: {count}")

    if failure_details:
        print(f"------------------------------------------------------------")
        print(f"  Strict Failures ({len(failure_details)}):")
        for f in failure_details[:10]:
            print(f"    [{f['scenario_id']}] {f['name']}: {f['reason']}")
        if len(failure_details) > 10:
            print(f"    ... and {len(failure_details) - 10} more (see JSON report)")

    if diag_failures:
        print(f"------------------------------------------------------------")
        print(f"  True Semantic/Engine Failures in Diagnostic Mode ({len(diag_failures)}):")
        for f in diag_failures:
            print(f"    [{f['scenario_id']}] {f['name']}: {f['reason']}")

    report_data = {
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "corpus": "openCypher TCK",
            "git_commit": "677cbafabb8c3c5eed458fd3b1ec0daec8d67d23",
            "release_tag": "2024.3",
            "total_scenarios": total,
            "claimed_subset_scenarios": claimed_count,
            "strict_mode": {
                "passed": passed_count,
                "failed": failed_count,
                "unsupported": unsupported_count,
                "blocked": blocked_count,
                "claimed_pass_rate_pct": round(pass_rate_claimed, 2),
                "overall_coverage_pct": round(overall_coverage, 2),
            },
            "diagnostic_mode": {
                "passed": diag_passed,
                "failed": diag_failed,
                "unsupported": unsupported_count,
                "blocked": blocked_count,
                "claimed_pass_rate_pct": round(diag_pass_rate, 2),
                "naming_drift_passed": diag_passed - passed_count,
            },
            "passed": passed_count,
            "failed": failed_count,
            "unsupported": unsupported_count,
            "blocked": blocked_count,
            "claimed_pass_rate_pct": round(pass_rate_claimed, 2),
            "overall_coverage_pct": round(overall_coverage, 2),
            "duration_seconds": round(total_time, 2),
        },
        "category_breakdown": {k: dict(v) for k, v in by_category.items()},
        "unsupported_breakdown": dict(unsupported_reasons.most_common()),
        "strict_failures": failure_details,
        "diagnostic_failures": diag_failures,
        "failures": failure_details,
        "scenarios": results,
    }

    with open(output_json, "w", encoding="utf-8") as fp:
        json.dump(report_data, fp, indent=2)

    print(f"")
    print(f"  Wrote raw TCK results to: {output_json}")
    print(f"============================================================")

    return report_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run openCypher TCK Compatibility Suite")
    parser.add_argument("--tck-dir", default=str(DEFAULT_TCK_DIR), help="Path to openCypher TCK features directory")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_JSON), help="Output JSON path")
    parser.add_argument("--filter", default=None, help="Filter feature files by substring")
    parser.add_argument("--max", type=int, default=None, help="Max scenarios to run")
    args = parser.parse_args()

    data = run_tck_suite(
        tck_dir=args.tck_dir,
        output_json=args.output,
        feature_filter=args.filter,
        max_scenarios=args.max,
    )
    # Return code 0 even if strict has naming differences, report cleanly
    sys.exit(0)
