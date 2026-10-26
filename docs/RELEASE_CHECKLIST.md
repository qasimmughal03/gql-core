# GQL-Core Release Gate Checklist

**Target Release**: `0.2.0a1` (Public Alpha Release)  
**Branch**: `feat/implementation`  
**Evaluation Date**: October 26, 2026  
**Auditor**: Principal Database & Release Engineer  
**Machine-Readable Evidence**: `benchmark/results/tck_compatibility_results.json`, `benchmark/results/snb_interactive_results.json`

---

## 1. Release Gate Criteria & Sign-Off

| # | Acceptance Criterion | Verification Method | Status | Measured Evidence |
|---|---|---|---|---|
| **1** | **TCK Harness Integrity Verified** | `tests/test_tck_harness_integrity.py` (12 counterexample & upstream tests) | **PASSED** | Side effects (`Create1`, `Delete1`), error categories & phases, fixture separation, exact result semantics, and full `Scenario Outline` expansion enforced. |
| **2** | **All 3,897 upstream scenarios classified & interpreted** | Automated runner (`benchmark/tck/runner.py`) | **PASSED** | **3,897 concrete scenarios** (1,339 regular + 2,558 outline expansions), **0 `BLOCKED` / uninterpreted steps**, **18 `UNSUPPORTED`**. |
| **3** | **Zero known wrong results within declared supported contract** | Strict TCK execution (`benchmark/results/tck_compatibility_results.json`) | **PASSED** | Full 3,897 corpus: **3,879 / 3,879 (100.00%)** pass (`0 FAIL_WRONG_RESULT`, `0 FAIL_COMPILE`, `0 FAIL_RUNTIME`, `0` side-effect failures, `0` error phase/category mismatches). Non-outline corpus: **1,321 / 1,321 (100.00%)** pass. |
| **4** | **Full project unit & counterexample test suite passes** | `python -m pytest tests/` | **PASSED** | **341 / 341 passed (100.0%)** in 25.8s including 12 harness integrity counterexample tests. |
| **5** | **Official supported LDBC queries produce verified correct answers** | Official LDBC SNB SF0.1 runner (`benchmark/snb/runner.py`) | **PASSED** | **4 / 4 official operations** (`IS1_p1`, `IS1_p2`, `IS3_p1`, `IS3_p2`) and **7 / 7 total queries** verified `VERIFIED_EXACT_MATCH` against SQLite Answer Oracle on 327,588 nodes and 1,477,965 edges. |
| **6** | **Wheel and sdist build and verify cleanly** | `python -m build` & artifact inspection | **PASSED** | `gql_core-0.2.0a1-py3-none-any.whl` and `gql_core-0.2.0a1.tar.gz` built and verified for version `0.2.0a1`. |
| **7** | **Documentation regenerated from machine-readable results** | `RELEASE_CORRECTNESS_REPORT.md`, `TCK_FAILURE_ANALYSIS.md`, `RELEASE_CHECKLIST.md` | **PASSED** | All reports regenerated directly from `benchmark/results/tck_compatibility_results.json`. |

---

## 2. Release Acceptance Sign-Off

### Verdict: **APPROVED FOR RELEASE (`0.2.0a1`)**

The verification harness enforces all upstream assertions with zero false positives. All 3,879 declared supported concrete scenarios in the openCypher TCK pass under strict side-effect tracking, exact result matching, and compile-time/runtime phase and error category checks. All 341 unit and regression tests pass, and official LDBC SNB SF0.1 benchmark queries match the reference relational oracle.
