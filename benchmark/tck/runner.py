"""openCypher TCK Compatibility Test Runner.

Inventories the full upstream openCypher TCK corpus (including Scenario Outline
expansions), classifies scenarios against the declared GQL-Core v0.2.0 language
contract, executes supported scenarios via the strict verification harness, and
writes an evidence-based JSON report.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from benchmark.tck.gherkin_parser import TCKScenario, parse_feature_file
from benchmark.tck.tck_adapter import run_scenario

DEFAULT_TCK_DIR = Path("benchmark/cache/openCypher/tck/features")
DEFAULT_OUTPUT_JSON = Path("benchmark/results/tck_compatibility_results.json")


def _compute_subset_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    cls_counts = Counter(r["primary_classification"] for r in results)
    unsupp_count = cls_counts["UNSUPPORTED"]
    blocked_count = cls_counts["BLOCKED"]
    supported_count = total - unsupp_count - blocked_count

    pass_result = cls_counts["PASS_RESULT"]
    pass_error = cls_counts["PASS_EXPECTED_ERROR"]
    fail_wrong_result = cls_counts["FAIL_WRONG_RESULT"]
    fail_compile = cls_counts["FAIL_COMPILE"]
    fail_runtime = cls_counts["FAIL_RUNTIME"]
    total_passed = pass_result + pass_error
    total_failed = fail_wrong_result + fail_compile + fail_runtime

    # Side-effect and error-category specific counters
    passed_side_effect_checks = sum(
        1 for r in results if r["primary_classification"] == "PASS_RESULT" and r.get("side_effect_checked", False)
    )
    passed_mutation_side_effect_checks = sum(
        1 for r in results if r["primary_classification"] == "PASS_RESULT" and r.get("has_mutation_side_effects", False)
    )
    failed_side_effect_checks = sum(
        1 for r in results if r.get("side_effect_failure", False)
    )
    wrong_error_categories = sum(
        1 for r in results if r.get("error_mismatch", False)
    )

    res_scenarios_count = sum(
        1
        for r in results
        if r.get("primary_classification") not in ("UNSUPPORTED", "BLOCKED")
        and r.get("expected_kind") in ("result", "empty")
    )
    err_scenarios_count = supported_count - res_scenarios_count

    res_accuracy = (pass_result / res_scenarios_count * 100.0) if res_scenarios_count > 0 else 0.0
    err_accuracy = (pass_error / err_scenarios_count * 100.0) if err_scenarios_count > 0 else 0.0
    lang_coverage = (supported_count / total * 100.0) if total > 0 else 0.0
    strict_compat = (total_passed / total * 100.0) if total > 0 else 0.0
    supported_pass_rate = (total_passed / supported_count * 100.0) if supported_count > 0 else 0.0

    return {
        "total_scenarios": total,
        "supported_scenarios": supported_count,
        "unsupported_scenarios": unsupp_count,
        "blocked_scenarios": blocked_count,
        "language_coverage_pct": round(lang_coverage, 2),
        "result_expecting_scenarios": res_scenarios_count,
        "error_expecting_scenarios": err_scenarios_count,
        "PASS_RESULT": pass_result,
        "PASS_EXPECTED_ERROR": pass_error,
        " passed_all_side_effect_checks": passed_side_effect_checks,
        "passed_mutation_side_effect_checks": passed_mutation_side_effect_checks,
        "failed_side_effect_checks": failed_side_effect_checks,
        "FAIL_WRONG_RESULT": fail_wrong_result,
        "FAIL_COMPILE": fail_compile,
        "FAIL_RUNTIME": fail_runtime,
        "wrong_error_categories": wrong_error_categories,
        "UNSUPPORTED": unsupp_count,
        "BLOCKED": blocked_count,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "pass_rate_supported_pct": round(supported_pass_rate, 2),
        "result_accuracy_pct": round(res_accuracy, 2),
        "expected_error_accuracy_pct": round(err_accuracy, 2),
        "strict_compatibility_pct": round(strict_compat, 2),
    }


def run_tck_suite(
    tck_dir: Path | str = DEFAULT_TCK_DIR,
    output_json: Path | str = DEFAULT_OUTPUT_JSON,
    feature_filter: str | None = None,
    max_scenarios: int | None = None,
    expand_outlines: bool = True,
) -> dict[str, Any]:
    tck_dir = Path(tck_dir)
    output_json = Path(output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    if not tck_dir.exists():
        raise FileNotFoundError(f"openCypher TCK directory not found at {tck_dir}. Run git clone first.")

    feature_files = sorted(tck_dir.rglob("*.feature"))
    if feature_filter:
        feature_files = [f for f in feature_files if feature_filter.lower() in f.as_posix().lower()]

    print("============================================================")
    print("  openCypher TCK Compatibility Suite (pinned to 2024.3)")
    print("============================================================")
    print(f"  Found {len(feature_files)} feature files in {tck_dir}")

    all_scenarios: list[TCKScenario] = []
    for ff in feature_files:
        scs = parse_feature_file(ff, expand_outlines=expand_outlines)
        all_scenarios.extend(scs)

    if max_scenarios:
        all_scenarios = all_scenarios[:max_scenarios]

    regular_count = sum(1 for s in all_scenarios if not s.is_outline)
    outline_count = sum(1 for s in all_scenarios if s.is_outline)
    print(f"  Total Scenarios Inventoried: {len(all_scenarios)} (Regular: {regular_count}, Outline Expansions: {outline_count})")
    print("------------------------------------------------------------")

    results: list[dict[str, Any]] = []
    unsupported_reasons = Counter()
    strict_failures: list[dict[str, Any]] = []
    by_category = defaultdict(lambda: Counter())

    start_time = time.perf_counter()

    for sc in all_scenarios:
        res_strict = run_scenario(sc, relaxed_columns=False)
        res_strict["is_outline"] = sc.is_outline
        strict_cls = res_strict["primary_classification"]

        rel_cat = Path(sc.file_path).parent.relative_to(tck_dir).as_posix().split("/")[0]
        by_category[rel_cat][strict_cls] += 1

        if strict_cls == "UNSUPPORTED":
            unsupported_reasons[res_strict.get("reason", "UNKNOWN")] += 1
        elif strict_cls in ("FAIL_WRONG_RESULT", "FAIL_COMPILE", "FAIL_RUNTIME", "BLOCKED"):
            strict_failures.append({
                "scenario_id": sc.scenario_id,
                "is_outline": sc.is_outline,
                "name": sc.name,
                "file": str(Path(sc.file_path).name),
                "query": sc.query,
                "primary_classification": strict_cls,
                "error_mismatch": res_strict.get("error_mismatch", False),
                "side_effect_failure": res_strict.get("side_effect_failure", False),
                "reason": res_strict.get("reason"),
                "expected_rows": res_strict.get("expected_rows"),
                "actual_rows": res_strict.get("actual_rows"),
            })

        results.append(res_strict)

    total_time = time.perf_counter() - start_time

    full_metrics = _compute_subset_metrics(results)
    non_outline_results = [r for r in results if not r.get("is_outline", False)]
    non_outline_metrics = _compute_subset_metrics(non_outline_results)

    print(f"  Execution complete in {total_time:.2f}s")
    print("")
    print("  ============================================================")
    print("  TCK HARNESS INTEGRITY METRICS (Full Expanded Corpus: 3,897)")
    print("  ============================================================")
    print(f"  Total Scenarios:                     {full_metrics['total_scenarios']}")
    print(f"  Supported Scenarios:                 {full_metrics['supported_scenarios']} ({full_metrics['language_coverage_pct']:.2f}%)")
    print(f"  Passed Result Checks (PASS_RESULT):  {full_metrics['PASS_RESULT']}")
    print(f"  Passed Expected-Error Checks:        {full_metrics['PASS_EXPECTED_ERROR']}")
    print(f"  Passed Mutation Side-Effect Checks:  {full_metrics['passed_mutation_side_effect_checks']} (Total SE checks passed: {full_metrics[' passed_all_side_effect_checks']})")
    print(f"  Failed Results (FAIL_WRONG_RESULT):  {full_metrics['FAIL_WRONG_RESULT']} (Side-effect failures: {full_metrics['failed_side_effect_checks']})")
    print(f"  Failed Compile (FAIL_COMPILE):       {full_metrics['FAIL_COMPILE']}")
    print(f"  Failed Runtime (FAIL_RUNTIME):       {full_metrics['FAIL_RUNTIME']}")
    print(f"  Wrong Error Categories / Phases:     {full_metrics['wrong_error_categories']}")
    print(f"  Blocked / Uninterpreted Scenarios:   {full_metrics['BLOCKED']}")
    print(f"  Unsupported Scenarios:               {full_metrics['UNSUPPORTED']}")
    print(f"  Supported Pass Rate:                 {full_metrics['pass_rate_supported_pct']:.2f}% ({full_metrics['total_passed']}/{full_metrics['supported_scenarios']})")
    print(f"  Result Accuracy:                     {full_metrics['result_accuracy_pct']:.2f}% ({full_metrics['PASS_RESULT']}/{full_metrics['result_expecting_scenarios']})")
    print(f"  Expected-Error Accuracy:             {full_metrics['expected_error_accuracy_pct']:.2f}% ({full_metrics['PASS_EXPECTED_ERROR']}/{full_metrics['error_expecting_scenarios']})")
    print("------------------------------------------------------------")
    print("  NON-OUTLINE CORPUS (1,339 Regular Scenarios — Direct Before/After Comparison):")
    print(f"  Total Non-Outline Scenarios:         {non_outline_metrics['total_scenarios']}")
    print(f"  Supported Non-Outline Scenarios:     {non_outline_metrics['supported_scenarios']}")
    print(f"  Passed Result Checks (PASS_RESULT):  {non_outline_metrics['PASS_RESULT']}")
    print(f"  Passed Expected-Error Checks:        {non_outline_metrics['PASS_EXPECTED_ERROR']}")
    print(f"  Passed Mutation Side-Effect Checks:  {non_outline_metrics['passed_mutation_side_effect_checks']} (Total SE checks passed: {non_outline_metrics[' passed_all_side_effect_checks']})")
    print(f"  Failed Results (FAIL_WRONG_RESULT):  {non_outline_metrics['FAIL_WRONG_RESULT']} (Side-effect failures: {non_outline_metrics['failed_side_effect_checks']})")
    print(f"  Failed Compile (FAIL_COMPILE):       {non_outline_metrics['FAIL_COMPILE']}")
    print(f"  Failed Runtime (FAIL_RUNTIME):       {non_outline_metrics['FAIL_RUNTIME']}")
    print(f"  Wrong Error Categories / Phases:     {non_outline_metrics['wrong_error_categories']}")
    print(f"  Blocked / Uninterpreted Scenarios:   {non_outline_metrics['BLOCKED']}")
    print(f"  Unsupported Scenarios:               {non_outline_metrics['UNSUPPORTED']}")
    print(f"  Supported Pass Rate (Non-Outline):   {non_outline_metrics['pass_rate_supported_pct']:.2f}% ({non_outline_metrics['total_passed']}/{non_outline_metrics['supported_scenarios']})")
    print("------------------------------------------------------------")
    print("  Breakdown by Category (Full Corpus):")
    for cat, counts in sorted(by_category.items()):
        c_tot = sum(counts.values())
        print(
            f"    {cat:<25}: tot={c_tot:<4} PASS_RES={counts['PASS_RESULT']:<4} "
            f"PASS_ERR={counts['PASS_EXPECTED_ERROR']:<4} WRONG={counts['FAIL_WRONG_RESULT']:<4} "
            f"COMP={counts['FAIL_COMPILE']:<4} RUN={counts['FAIL_RUNTIME']:<4} "
            f"BLK={counts['BLOCKED']:<3} UNSUPP={counts['UNSUPPORTED']:<4}"
        )

    report_data = {
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "corpus": "openCypher TCK",
            "git_commit": "677cbafabb8c3c5eed458fd3b1ec0daec8d67d23",
            "release_tag": "2024.3",
            "total_scenarios": full_metrics["total_scenarios"],
            "regular_scenarios": regular_count,
            "outline_expanded_scenarios": outline_count,
            "supported_scenarios": full_metrics["supported_scenarios"],
            "unsupported_scenarios": full_metrics["unsupported_scenarios"],
            "blocked_scenarios": full_metrics["blocked_scenarios"],
            "language_coverage_pct": full_metrics["language_coverage_pct"],
            "result_expecting_scenarios": full_metrics["result_expecting_scenarios"],
            "error_expecting_scenarios": full_metrics["error_expecting_scenarios"],
            "strict_mode": full_metrics,
            "non_outline_strict_mode": non_outline_metrics,
            "duration_seconds": round(total_time, 2),
        },
        "category_breakdown": {k: dict(v) for k, v in by_category.items()},
        "unsupported_breakdown": dict(unsupported_reasons.most_common()),
        "strict_failures": strict_failures,
        "scenarios": results,
    }

    with open(output_json, "w", encoding="utf-8") as fp:
        json.dump(report_data, fp, indent=2)

    print("")
    print(f"  Wrote raw TCK results to: {output_json}")
    print("============================================================")
    return report_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run openCypher TCK Compatibility Suite")
    parser.add_argument("--tck-dir", default=str(DEFAULT_TCK_DIR), help="Path to openCypher TCK features directory")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_JSON), help="Output JSON path")
    parser.add_argument("--filter", default=None, help="Filter feature files by substring")
    parser.add_argument("--max", type=int, default=None, help="Max scenarios to run")
    parser.add_argument("--no-outlines", action="store_true", help="Skip Scenario Outline expansions")
    args = parser.parse_args()

    run_tck_suite(
        tck_dir=args.tck_dir,
        output_json=args.output,
        feature_filter=args.filter,
        max_scenarios=args.max,
        expand_outlines=not args.no_outlines,
    )
    sys.exit(0)
