# GQL-Core Release Correctness Report

**Release Target**: `0.2.0a1`  
**Date**: October 19, 2026  
**Auditor**: Principal Database & Release Engineering  
**Branch**: `feat/implementation`  
**Repository**: `qasimmughal03/knowledge-graoh-with-formal-query`  
**Source of Truth**: `benchmark/results/tck_compatibility_results.json`, `benchmark/results/snb_interactive_results.json`

---

## 1. Executive Summary & Release Verdict

A comprehensive release gate audit and compiler/executor remediation cycle was completed on GQL-Core across all six phases mandated by the release charter. All metrics below are generated directly from the machine-readable benchmark output files (`benchmark/results/tck_compatibility_results.json` and `benchmark/results/snb_interactive_results.json`).

### Verdict: **READY FOR EXPERIMENTAL RELEASE (`0.2.0a1`)**

The engine satisfies all 8 acceptance criteria for public experimental alpha publication:
- **100% Supported-Subset Accuracy**: Out of **1,321** declared supported scenarios in the upstream openCypher TCK (98.66% of the 1,339-scenario corpus), **1,321 pass strictly** (`1,176 PASS_RESULT` + `145 PASS_EXPECTED_ERROR`), with **0 wrong results (`FAIL_WRONG_RESULT = 0`)**, **0 compile failures (`FAIL_COMPILE = 0`)**, **0 runtime failures (`FAIL_RUNTIME = 0`)**, and **0 blocked scenarios (`BLOCKED = 0`)**.
- **Explicit Unsupported Contract**: The remaining **18** scenarios (1.34% of the corpus) use features explicitly excluded from the `0.2.0a1` query contract (`CORRELATED_SUBQUERY_EXISTS`: 10 scenarios; `MULTI_REL_TYPE_DISJUNCTION`: 8 scenarios) and are rejected deterministically.
- **100% Unit & Regression Test Pass Rate**: All **325** unit, integration, differential, and regression tests in `tests/` pass (`325 passed`).
- **100% Official LDBC SNB SF0.1 Oracle Verification**: All 4 official LDBC SNB Interactive v1 operations (`IS1_p1`, `IS1_p2`, `IS3_p1`, `IS3_p2`) plus 3 diagnostic complex read queries (`IS5`, `IC2`, `IC8`) achieve `VERIFIED_EXACT_MATCH` against the independent SQLite relational oracle on the full SF0.1 dataset (327,588 nodes, 1,477,965 edges).
- **Clean-Room Packaging Verified**: Both wheel (`gql_core-0.2.0a1-py3-none-any.whl`) and sdist (`gql_core-0.2.0a1.tar.gz`) pass `twine check` and execute cleanly in an isolated virtual environment outside the repository checkout.

---

## 2. Before / After Comparison Table

The table below compares the initial unverified baseline against the final verified release gate measurements recorded in `benchmark/results/tck_compatibility_results.json`:

| Metric | Before (Initial Report) | Prior Audit Snapshot | Final Verified Release Gate | Status / Delta |
|---|---|---|---|---|
| **Total Upstream Scenarios** | 1,338 (claimed) / 1,339 | 1,339 | **1,339** | Verified across 220 `.feature` files |
| **Supported Scenarios** | Unclassified | 1,321 | **1,321** (98.66% coverage) | Explicit Contract (`SUPPORTED_QUERY_CONTRACT.md`) |
| **Unsupported Scenarios (`UNSUPPORTED`)** | Unclassified | 18 | **18** (1.34%) | Correlated `EXISTS` (10), Multi-rel `[:A\|B]` (8) |
| **Correct Result Scenarios (`PASS_RESULT`)** | 950 (unverified) | 1,066 | **1,176** | **+226 verified result passes (+23.8%)** |
| **Correct Expected-Error Scenarios (`PASS_EXPECTED_ERROR`)** | ~0 (conflated) | 98 | **145** | **145 / 145 negative tests rejected (100%)** |
| **Wrong Results (`FAIL_WRONG_RESULT`)** | 132 reported | 157 (110 res + 47 err) | **0** | **100% eliminated within supported contract** |
| **Compile Failures (`FAIL_COMPILE`)** | 190 reported | 0 | **0** | **100% eliminated (-190)** |
| **Runtime Failures (`FAIL_RUNTIME`)** | 65 reported | 0 | **0** | **100% eliminated (-65)** |
| **Blocked Scenarios (`BLOCKED`)** | 2 reported | 0 | **0** | **0 blocked fixtures** |
| **Result Accuracy (Supported)** | Unvalidated | 90.65% (1,066 / 1,176) | **100.00% (1,176 / 1,176)** | Exact column names & cell values |
| **Expected-Error Accuracy (Supported)** | Unvalidated | 67.59% (98 / 145) | **100.00% (145 / 145)** | All invalid queries rejected |
| **Supported-Subset Accuracy (Strict)** | Unvalidated | 88.12% (1,164 / 1,321) | **100.00% (1,321 / 1,321)** | Zero known wrong outputs |
| **Total Corpus Strict Compatibility** | Unvalidated | 86.93% (1,164 / 1,339) | **98.66% (1,321 / 1,339)** | Across all 1,339 upstream scenarios |
| **Diagnostic Compatibility** | Unvalidated | 86.93% (1,164 / 1,339) | **98.66% (1,321 / 1,339)** | 0 column-naming drift scenarios |
| **Project Unit Tests (`pytest tests/`)** | 303 reported | 320 | **325 / 325 (100%)** | +22 release-gate regression & differential tests |
| **LDBC SNB SF0.1 Official Correctness** | Unverified | 4 / 4 | **4 / 4 Official (7 / 7 Total)** | 100% exact match vs SQLite Oracle |

---

## 3. Category Breakdown (Strict Mode)

From `benchmark/results/tck_compatibility_results.json`:

| TCK Category | Total Scenarios | `PASS_RESULT` | `PASS_EXPECTED_ERROR` | `FAIL_WRONG_RESULT` | `FAIL_COMPILE` | `FAIL_RUNTIME` | `UNSUPPORTED` |
|---|---|---|---|---|---|---|---|
| **clauses** | 753 | 649 | 100 | 0 | 0 | 0 | 4 |
| **expressions** | 556 | 499 | 45 | 0 | 0 | 0 | 12 |
| **useCases** | 30 | 28 | 0 | 0 | 0 | 0 | 2 |
| **Total** | **1,339** | **1,176** | **145** | **0** | **0** | **0** | **18** |

---

## 4. Summary of Root-Cause Remediations

1. **Chained vs. Parenthesized Comparisons (`Comparison4#1`, `List11#3`)**:
   - Tracked parenthesized AST nodes (`paren_expr`) in `CypherPipelineTransformer` so unparenthesized chained comparisons (`a < b = c <> d`) expand into conjunctive pairwise comparisons `(a < b) AND (b = c) AND (c <> d)`, while parenthesized boolean expressions (`((size(list) = 0) = empty)`) evaluate directly as boolean equality.

2. **Multi-Label Node Matching & Predicates (`Match1#3`, `Match7#25`, `MatchWhere1#1-2`, `Graph5#1-5`)**:
   - Fixed `label_check_op` in `parser.py` to construct `ASTAnd` over `HAS_LABEL` calls for conjunctive label predicates (`WHERE n:A:B`, `RETURN n:A:B`).
   - Updated `_is_pipeline_query` in `executor.py` to route multi-label patterns, inline relationship property filters, and parameterized `WHERE` clauses through the full multi-clause pipeline executor.

3. **Semantic Validation & Expected-Error Enforcement (All 47 Negative Test Failures Fixed)**:
   - Removed a shadowing inner `from gql_core.ir import Arithmetic` import inside `validate_query` in `semantic.py` that previously triggered an `UnboundLocalError` across 39 `DELETE` and `MERGE` validation paths.
   - Enforced mandatory aliasing for non-variable expressions in `WITH` clauses (`With4#5`).
   - Rejected pattern predicates on the right-hand side of `SET` assignments (`Pattern1#24`).
   - Rejected property access on `Path` variables (`MatchWhere1#14`), bare entity variables in boolean `WHERE` contexts (`Pattern1#11`), and rebinding `list`/`edge`/`path` variables as node patterns in `MATCH` (`Match3#30`).
   - Fixed `RETURN DISTINCT` + `ORDER BY` validation so `RETURN DISTINCT a.name` only exposes `a.name` (and not unrelated properties like `a.age`) to `ORDER BY` (`ReturnOrderBy2#13`).

4. **Pipeline Scoping, Aggregation, and Set Operations (`Call6#1`, `Unwind1#6`, `Union1#1`, `ReturnOrderBy4#2`)**:
   - Fixed `has_star` detection in `WITH` and `RETURN` so `count(*)` is not mistaken for `WITH *`, preventing out-of-scope variable leakage into subsequent `CALL ... YIELD` clauses (`Call6#1`).
   - Evaluated dynamic expressions (such as `UNWIND` loop variables) inside inline node and relationship property filters in `_match_path_pattern` (`Unwind1#6`).
   - Deduplicated both left and right input branches in distinct `UNION` queries and aligned cross-type `ORDER BY` hierarchy so Lists sort before Paths (`Union1#1`, `ReturnOrderBy4#2`).
   - Preserved pre-projection row bindings alongside projected aliases during `ORDER BY` evaluation after aggregation (`ReturnOrderBy` / `WithOrderBy`).

5. **Temporal Timezone Offsets & Large ISO Durations (`Temporal5#6`, `Temporal6#7`, `Temporal10#10`)**:
   - Added deterministic CET/CEST timezone offset and `epochSeconds`/`epochMillis` calculation in `evaluator.py` for environments without system IANA `tzdata` packages, and formatted large `duration.inSeconds` outputs according to openCypher's `PT...H...M...S` decomposition.

---

## 5. Verification & Reproduction Commands

```bash
# 1. Run the complete unit, integration, and regression suite (325 tests)
python -m pytest tests/

# 2. Run the openCypher TCK compatibility suite (1,339 scenarios)
python -m benchmark.tck.runner

# 3. Run the official LDBC SNB SF0.1 benchmark with SQLite Answer Oracle
python -m benchmark.snb.runner

# 4. Build and verify wheel and sdist packages in a clean environment
python -m build
python -m twine check dist/*
```
