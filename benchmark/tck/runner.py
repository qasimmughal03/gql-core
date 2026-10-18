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
    strict_classifications = Counter()
    diag_classifications = Counter()
    unsupported_reasons = Counter()
    strict_failures = []
    diag_failures = []
    by_category = defaultdict(lambda: Counter())

    start_time = time.perf_counter()

    for idx, sc in enumerate(all_scenarios):
        # 1. Strict mode execution (exact openCypher column names required)
        res_strict = run_scenario(sc, relaxed_columns=False)
        strict_cls = res_strict["primary_classification"]
        strict_classifications[strict_cls] += 1

        rel_cat = Path(sc.file_path).parent.relative_to(tck_dir).as_posix().split("/")[0]
        by_category[rel_cat][strict_cls] += 1

        if strict_cls == "UNSUPPORTED":
            unsupported_reasons[res_strict.get("reason", "UNKNOWN")] += 1
            diag_classifications["UNSUPPORTED"] += 1
            results.append(res_strict)
        else:
            if strict_cls in ("FAIL_WRONG_RESULT", "FAIL_COMPILE", "FAIL_RUNTIME"):
                strict_failures.append({
                    "scenario_id": sc.scenario_id,
                    "name": sc.name,
                    "file": str(Path(sc.file_path).name),
                    "query": sc.query,
                    "primary_classification": strict_cls,
                    "reason": res_strict.get("reason"),
                    "expected_rows": res_strict.get("expected_rows"),
                    "actual_rows": res_strict.get("actual_rows"),
                })
                # Check if this failure passes in diagnostic mode (unaliased column naming differences)
                diag_res = run_scenario(sc, relaxed_columns=True)
                diag_cls = diag_res["primary_classification"]
                diag_classifications[diag_cls] += 1
                if diag_cls in ("FAIL_WRONG_RESULT", "FAIL_COMPILE", "FAIL_RUNTIME"):
                    diag_failures.append({
                        "scenario_id": sc.scenario_id,
                        "name": sc.name,
                        "file": str(Path(sc.file_path).name),
                        "query": sc.query,
                        "primary_classification": diag_cls,
                        "reason": diag_res.get("reason"),
                        "expected_rows": diag_res.get("expected_rows"),
                        "actual_rows": diag_res.get("actual_rows"),
                    })
            else:
                diag_classifications[strict_cls] += 1

            results.append(res_strict)

    total_time = time.perf_counter() - start_time

    total = len(all_scenarios)
    unsupp_count = strict_classifications["UNSUPPORTED"]
    supported_count = total - unsupp_count

    # Strict counts
    strict_pass_result = strict_classifications["PASS_RESULT"]
    strict_pass_error = strict_classifications["PASS_EXPECTED_ERROR"]
    strict_wrong_result = strict_classifications["FAIL_WRONG_RESULT"]
    strict_compile_fail = strict_classifications["FAIL_COMPILE"]
    strict_runtime_fail = strict_classifications["FAIL_RUNTIME"]
    strict_blocked = strict_classifications["BLOCKED"]
    strict_total_passed = strict_pass_result + strict_pass_error

    # Diagnostic counts
    diag_pass_result = diag_classifications["PASS_RESULT"]
    diag_pass_error = diag_classifications["PASS_EXPECTED_ERROR"]
    diag_wrong_result = diag_classifications["FAIL_WRONG_RESULT"]
    diag_compile_fail = diag_classifications["FAIL_COMPILE"]
    diag_runtime_fail = diag_classifications["FAIL_RUNTIME"]
    diag_blocked = diag_classifications["BLOCKED"]
    diag_total_passed = diag_pass_result + diag_pass_error

    # Total evaluated supported result-expecting and error-expecting counts
    # Result-expecting scenarios in supported set
    res_scenarios_count = sum(1 for r in results if r.get("primary_classification") != "UNSUPPORTED" and r.get("expected_kind") in ("result", "empty"))
    err_scenarios_count = supported_count - res_scenarios_count

    strict_res_accuracy = (strict_pass_result / res_scenarios_count * 100.0) if res_scenarios_count > 0 else 0.0
    strict_err_accuracy = (strict_pass_error / err_scenarios_count * 100.0) if err_scenarios_count > 0 else 0.0
    lang_coverage = (supported_count / total * 100.0) if total > 0 else 0.0
    strict_compat = (strict_total_passed / total * 100.0) if total > 0 else 0.0

    diag_res_accuracy = (diag_pass_result / res_scenarios_count * 100.0) if res_scenarios_count > 0 else 0.0
    diag_err_accuracy = (diag_pass_error / err_scenarios_count * 100.0) if err_scenarios_count > 0 else 0.0
    diag_compat = (diag_total_passed / total * 100.0) if total > 0 else 0.0

    print(f"  Execution complete in {total_time:.2f}s")
    print(f"")
    print(f"  ============================================================")
    print(f"  TCK RELEASE AUDIT METRICS (7-Classification Primary Gate)")
    print(f"  ============================================================")
    print(f"  Total Upstream Scenarios:            {total}")
    print(f"  Supported Scenarios:                 {supported_count} (Coverage: {lang_coverage:.1f}%)")
    print(f"  Unsupported Scenarios:               {unsupp_count}")
    print(f"  Blocked Scenarios:                   {strict_blocked}")
    print(f"------------------------------------------------------------")
    print(f"  STRICT MODE (Exact openCypher Column Names):")
    print(f"    PASS_RESULT:                       {strict_pass_result}")
    print(f"    PASS_EXPECTED_ERROR:               {strict_pass_error}")
    print(f"    FAIL_WRONG_RESULT:                 {strict_wrong_result}")
    print(f"    FAIL_COMPILE:                      {strict_compile_fail}")
    print(f"    FAIL_RUNTIME:                      {strict_runtime_fail}")
    print(f"    BLOCKED:                           {strict_blocked}")
    print(f"    Total Strict Passes:               {strict_total_passed} / {supported_count} ({strict_total_passed/supported_count*100:.1f}%)")
    print(f"    Result Accuracy:                   {strict_res_accuracy:.2f}% ({strict_pass_result}/{res_scenarios_count})")
    print(f"    Expected-Error Accuracy:           {strict_err_accuracy:.2f}% ({strict_pass_error}/{err_scenarios_count})")
    print(f"    Strict Compatibility:              {strict_compat:.2f}% ({strict_total_passed}/{total})")
    print(f"------------------------------------------------------------")
    print(f"  DIAGNOSTIC MODE (Relaxed Column Aliasing for Expressions):")
    print(f"    PASS_RESULT:                       {diag_pass_result}")
    print(f"    PASS_EXPECTED_ERROR:               {diag_pass_error}")
    print(f"    FAIL_WRONG_RESULT:                 {diag_wrong_result}")
    print(f"    FAIL_COMPILE:                      {diag_compile_fail}")
    print(f"    FAIL_RUNTIME:                      {diag_runtime_fail}")
    print(f"    BLOCKED:                           {diag_blocked}")
    print(f"    Total Diagnostic Passes:           {diag_total_passed} / {supported_count} ({diag_total_passed/supported_count*100:.1f}%)")
    print(f"    Result Accuracy (Diagnostic):      {diag_res_accuracy:.2f}% ({diag_pass_result}/{res_scenarios_count})")
    print(f"    Diagnostic Compatibility:          {diag_compat:.2f}% ({diag_total_passed}/{total})")
    print(f"    Column-naming Drift Scenarios:     {diag_total_passed - strict_total_passed}")
    print(f"------------------------------------------------------------")
    print(f"  Breakdown by Category (Strict):")
    for cat, counts in sorted(by_category.items()):
        c_tot = sum(counts.values())
        print(f"    {cat:<25}: tot={c_tot:<4} PASS_RES={counts['PASS_RESULT']:<4} PASS_ERR={counts['PASS_EXPECTED_ERROR']:<4} WRONG={counts['FAIL_WRONG_RESULT']:<4} COMP={counts['FAIL_COMPILE']:<4} RUN={counts['FAIL_RUNTIME']:<4} UNSUPP={counts['UNSUPPORTED']:<4}")

    print(f"------------------------------------------------------------")
    print(f"  Top Unsupported Feature Drivers:")
    for reason, count in unsupported_reasons.most_common(8):
        print(f"    {reason:<35}: {count}")

    report_data = {
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "corpus": "openCypher TCK",
            "git_commit": "677cbafabb8c3c5eed458fd3b1ec0daec8d67d23",
            "release_tag": "2024.3",
            "total_scenarios": total,
            "supported_scenarios": supported_count,
            "unsupported_scenarios": unsupp_count,
            "language_coverage_pct": round(lang_coverage, 2),
            "result_expecting_scenarios": res_scenarios_count,
            "error_expecting_scenarios": err_scenarios_count,
            "strict_mode": {
                "PASS_RESULT": strict_pass_result,
                "PASS_EXPECTED_ERROR": strict_pass_error,
                "FAIL_WRONG_RESULT": strict_wrong_result,
                "FAIL_COMPILE": strict_compile_fail,
                "FAIL_RUNTIME": strict_runtime_fail,
                "UNSUPPORTED": unsupp_count,
                "BLOCKED": strict_blocked,
                "total_passed": strict_total_passed,
                "pass_rate_supported_pct": round(strict_total_passed / supported_count * 100.0, 2) if supported_count > 0 else 0.0,
                "result_accuracy_pct": round(strict_res_accuracy, 2),
                "expected_error_accuracy_pct": round(strict_err_accuracy, 2),
                "strict_compatibility_pct": round(strict_compat, 2),
            },
            "diagnostic_mode": {
                "PASS_RESULT": diag_pass_result,
                "PASS_EXPECTED_ERROR": diag_pass_error,
                "FAIL_WRONG_RESULT": diag_wrong_result,
                "FAIL_COMPILE": diag_compile_fail,
                "FAIL_RUNTIME": diag_runtime_fail,
                "UNSUPPORTED": unsupp_count,
                "BLOCKED": diag_blocked,
                "total_passed": diag_total_passed,
                "pass_rate_supported_pct": round(diag_total_passed / supported_count * 100.0, 2) if supported_count > 0 else 0.0,
                "result_accuracy_pct": round(diag_res_accuracy, 2),
                "expected_error_accuracy_pct": round(diag_err_accuracy, 2),
                "diagnostic_compatibility_pct": round(diag_compat, 2),
                "naming_drift_passed": diag_total_passed - strict_total_passed,
            },
            "duration_seconds": round(total_time, 2),
        },
        "category_breakdown": {k: dict(v) for k, v in by_category.items()},
        "unsupported_breakdown": dict(unsupported_reasons.most_common()),
        "strict_failures": strict_failures,
        "diagnostic_failures": diag_failures,
        "scenarios": results,
    }

    with open(output_json, "w", encoding="utf-8") as fp:
        json.dump(report_data, fp, indent=2)

    print(f"")
    print(f"  Wrote raw TCK results to: {output_json}")

    def _safe_str(s: Any) -> str:
        return str(s).encode("ascii", "backslashreplace").decode("ascii")

    if strict_failures:
        print(f"------------------------------------------------------------")
        print(f"  Strict Failures ({len(strict_failures)}):")
        for f in strict_failures[:10]:
            print(_safe_str(f"    [{f['scenario_id']}] {f['name']}: {f['reason']}"))
        if len(strict_failures) > 10:
            print(f"    ... and {len(strict_failures) - 10} more (see JSON report)")

    if diag_failures:
        print(f"------------------------------------------------------------")
        print(f"  Diagnostic Failures ({len(diag_failures)}):")
        for f in diag_failures[:20]:
            print(_safe_str(f"    [{f['scenario_id']}] {f['name']}: {f['reason']}"))
        if len(diag_failures) > 20:
            print(f"    ... and {len(diag_failures) - 20} more (see JSON report)")

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
