# GQL-Core Release Gate Checklist

**Target Release**: `0.2.0a1` (Public Experimental Release)  
**Branch**: `feat/implementation`  
**Evaluation Date**: October 19, 2026  
**Auditor**: Principal Database & Release Engineer  
**Machine-Readable Evidence**: `benchmark/results/tck_compatibility_results.json`, `benchmark/results/snb_interactive_results.json`

---

## 1. Release Gate Criteria & Sign-Off

A release may proceed only if all 8 acceptance criteria are satisfied:

| # | Acceptance Criterion | Verification Method | Status | Measured Evidence |
|---|---|---|---|---|
| **1** | **All scenarios accurately classified** | Automated 7-classification runner on 1,339 TCK scenarios (`benchmark/tck/runner.py`) | **PASSED** | **1,176 `PASS_RESULT`**, **145 `PASS_EXPECTED_ERROR`**, **0 `FAIL_WRONG_RESULT`**, **0 `FAIL_COMPILE`**, **0 `FAIL_RUNTIME`**, **18 `UNSUPPORTED`**, **0 `BLOCKED`**. |
| **2** | **Zero known wrong results within declared supported contract** | Audited against `docs/SUPPORTED_QUERY_CONTRACT.md` | **PASSED** | **0 `FAIL_WRONG_RESULT`** across all 1,321 supported scenarios (100.00% result accuracy on 1,176 result-expecting scenarios; 100.00% expected-error accuracy on 145 negative scenarios). |
| **3** | **Remaining unsupported functionality fails explicitly** | Semantic validation & grammar compilation checks | **PASSED** | All 18 unsupported scenarios (`CORRELATED_SUBQUERY_EXISTS`: 10, `MULTI_REL_TYPE_DISJUNCTION`: 8) fail explicitly at compile time. |
| **4** | **Every fixed bug has a regression test** | `tests/test_release_gate_remediation.py` | **PASSED** | 22 dedicated regression and property-based differential tests covering every distinct root cause. |
| **5** | **Full project test suite passes** | `python -m pytest tests/` | **PASSED** | **325 / 325 passed (100.0%)** in 10.67s. |
| **6** | **Official supported LDBC queries produce verified correct answers** | Official LDBC SNB SF0.1 runner (`benchmark/snb/runner.py`) | **PASSED** | **4 / 4 official operations** (`IS1_p1`, `IS1_p2`, `IS3_p1`, `IS3_p2`) and **7 / 7 total queries** verified `VERIFIED_EXACT_MATCH` against SQLite Answer Oracle on 327,588 nodes and 1,477,965 edges. |
| **7** | **Wheel and sdist install and execute successfully** | Clean-room virtual environment (`scratch/verify_clean_packaging.py` & `twine check`) | **PASSED** | `gql_core-0.2.0a1-py3-none-any.whl` and `gql_core-0.2.0a1.tar.gz` pass `twine check` and execute CLI, Cypher, `PlanBuilder`, and Datalog inference in an isolated venv outside the repo. |
| **8** | **Documentation reflects implemented capabilities and measured limitations** | All 5 Release Gate Markdown docs regenerated from JSON results | **PASSED** | `RELEASE_CORRECTNESS_REPORT.md`, `TCK_FAILURE_ANALYSIS.md`, `SUPPORTED_QUERY_CONTRACT.md`, `PACKAGING_VERIFICATION.md`, and `RELEASE_CHECKLIST.md` synchronized. |

---

## 2. Release Acceptance Sign-Off

### Verdict: **READY FOR EXPERIMENTAL RELEASE (`0.2.0a1`)**

All 8 release gate criteria have been independently reproduced, measured, and verified with zero known wrong results within the declared supported contract.

### Manual Publishing Procedure (Do Not Automate Without Tag Approval):

```bash
# 1. Verify working tree is clean
git status

# 2. Build release artifacts
python -m build

# 3. Check distribution package integrity
python -m twine check dist/*

# 4. Upload to TestPyPI
python -m twine upload --repository testpypi dist/*

# 5. Upload to Production PyPI (when authorized)
python -m twine upload dist/*
```
