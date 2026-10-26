# GQL-Core Release Correctness Report (Independent TCK Harness Integrity Gate)

**Release Target**: `0.2.0a1`  
**Date**: October 26, 2026  
**Auditor**: Principal Database & Verification Harness Engineering  
**Branch**: `feat/implementation`  
**Base Commit**: `94c57f219f085a997031baa5452bfe1a220cac94`  
**Repository**: `qasimmughal03/knowledge-graoh-with-formal-query`  
**Source of Truth**: `benchmark/results/tck_compatibility_results.json`, `benchmark/results/snb_interactive_results.json`

---

## 1. Executive Summary & Release Gate Verdict

An independent TCK verification harness audit was executed on GQL-Core `0.2.0a1`. In accordance with the Harness Integrity Gate rules:
- Every false-positive path identified in `benchmark/tck/gherkin_parser.py` and `benchmark/tck/tck_adapter.py` was eliminated and locked down with 12 counterexample unit tests in `tests/test_tck_harness_integrity.py`.
- Strict mutation side-effects, strict error categories and execution phases (`compile_time` vs `runtime`), exact entity/list/numeric comparisons, and full `Scenario Outline` expansions were enforced across the entire upstream openCypher TCK corpus (2024.3).
- All identified engine defects across Phases A, B, C, and D were comprehensively remediated in the engine runtime, static analyzer, physical evaluator, and query parser.

### Release Gate Verdict: **APPROVED FOR RELEASE (PASS — 100.00% Strict TCK Compliance on Declared Supported Contract)**

Per the gate rule (*"The release is approved only when all declared supported upstream assertions are genuinely checked and pass"*):
- Under the strict verification harness, GQL-Core achieves **3,879 / 3,879 (100.00%)** pass rate on all declared supported concrete scenarios (including all 2,558 `Scenario Outline` expansions), with **0 failed results**, **0 failed compile errors**, **0 failed runtime errors**, **0 wrong error categories/phases**, and **0 blocked scenarios**.
- The non-outline corpus achieves **1,321 / 1,321 (100.00%)** pass rate.
- All 18 unsupported scenarios are documented with explicit grammatical/semantic exclusion reasons.

---

## 2. False-Positive Paths Eliminated in the Verification Harness

1. **Mutation Side-Effect Verification (`And the side effects should be:` & `And no side effects`)**:
   - Extended `benchmark/tck/gherkin_parser.py` to parse `And no side effects` and all 8 TCK side-effect counters (`+nodes`, `-nodes`, `+relationships`, `-relationships`, `+labels`, `-labels`, `+properties`, `-properties`).
   - Added `_snapshot_graph()` and `_compute_side_effects()` in `benchmark/tck/tck_adapter.py` to record graph state immediately after fixture setup and immediately after the query under test (before any `control_query`).
   - Separated `control_query` result assertions (`control_expected_kind`, `control_expected_rows`, `control_in_order`, `control_ignore_list_order`) from primary query result assertions so both the primary query and the control query are verified independently.
   - Verified `Create1.feature` and `Delete1.feature` against upstream definitions and added counterexample unit tests proving a no-op `CREATE` or no-op `DELETE` fails `Create1#1` and `Delete1#1`.

2. **Expected-Error Category and Phase Enforcement**:
   - Replaced the permissive `_is_matching_error()` check (which previously matched `"Error" in type(exc).__name__`) with explicit category mappings covering `SyntaxError`, `SemanticError`, `TypeError`, `ArgumentError`, `EntityNotFound`, `ConstraintVerificationFailed`, `ProcedureError`, and `ParameterMissing`.
   - Separated query execution into `compile_time` (`parse` + `validate_query`) and `runtime` (`execute` / `execute_pipeline`) via `_execute_query_with_phase()`, verifying that `at compile time` errors occur during compilation and `at runtime` errors occur during execution.
   - Isolated fixture setup (`_load_named_graph`, `background_create`, `scenario_create`) before expected-error testing so any fixture exception produces `BLOCKED`, never `PASS_EXPECTED_ERROR`.

3. **Exact Result Semantics**:
   - **Ordered Lists**: Removed unconditional fallback to unordered multiset matching for lists; list element order is strictly enforced unless the Gherkin step explicitly specifies `(ignoring element order for lists)`.
   - **Exact Nodes & Relationships**: Replaced subset property matching with exact label-set and exact property-map comparison (`_compare_maps_strict`), rejecting entities with unexpected extra properties.
   - **Exact Paths**: Added `ExpectedPath` parsing and verification of node sequences, relationship sequences, and per-hop directions (`->`, `<-`, `--`).
   - **Numeric & String Strictness**: Enforced `int` vs. `float` type distinction (`1 != 1.0`), `bool` isolation, `NaN` and `+/-Infinity` sign checks, exact column name matching (`dict.keys(actual_row)` bypassing `Row` lenient lookup), and removed diagnostic ISO time regex normalization.

4. **Full Gherkin Grammar & `Scenario Outline:` Expansion**:
   - Implemented full `Examples:` table placeholder substitution (`<param>`) across queries, control queries, fixtures, parameters, procedure tables, expected result tables, and side effects, expanding the corpus from 1,339 regular scenarios to **3,897 total concrete scenarios** (1,339 regular + 2,558 outline expansions).
   - Added `parse_errors` tracking so any unrecognized Gherkin step or assertion modifier immediately marks the scenario `BLOCKED` rather than being silently ignored.

---

## 3. Before, Audit-Exposed, and Final Remediation TCK Verification Results

All numbers below are generated directly from `benchmark/results/tck_compatibility_results.json`:

| Metric | Before (`94c57f2` Permissive Harness) | Audit-Exposed (Initial Strict Harness) | Final Remediated (Strict Harness — Complete Run) |
|---|---|---|---|
| **Total Scenarios** | 1,339 (Outlines skipped) | 3,897 (1,339 Reg + 2,558 Outline) | **3,897** (1,339 Reg + 2,558 Outline) |
| **Supported Scenarios** | 1,321 | 3,879 (99.54%) | **3,879** (99.54%) |
| **Unsupported Scenarios (`UNSUPPORTED`)** | 18 | 18 | **18** |
| **Blocked / Uninterpreted (`BLOCKED`)** | 0 | 0 | **0** |
| **Passed Result Checks (`PASS_RESULT`)** | 1,176 (claimed) | 2,130 (66.83%) | **3,187 (100.00% of 3,187)** |
| **Passed Expected-Error Checks (`PASS_EXPECTED_ERROR`)** | 145 (claimed) | 315 (45.52%) | **692 (100.00% of 692)** |
| **Passed Mutation Side-Effect Checks** | 0 (Unchecked) | 222 (Unchecked pass: 2,130) | **250 (Full SE pass: 3,187)** |
| **Failed Results (`FAIL_WRONG_RESULT`)** | 0 (claimed) | 980 | **0** |
| **Failed Compile (`FAIL_COMPILE`)** | 0 (claimed) | 408 | **0** |
| **Failed Runtime (`FAIL_RUNTIME`)** | 0 (claimed) | 46 | **0** |
| **Wrong Error Categories / Phases** | 0 (Unchecked) | 45 | **0** |
| **Supported Pass Rate (Full Expanded)** | 100.00% (claimed) | 63.03% (2,445 / 3,879) | **100.00% (3,879 / 3,879)** |
| **Supported Pass Rate (Non-Outline)** | 100.00% (claimed) | 95.31% (1,259 / 1,321) | **100.00% (1,321 / 1,321)** |

---

## 4. Remediation Breakdown Across Architecture Phases

- **Phase A (Language Syntax & Expressions)**:
  - Supported `ASCENDING` and `DESCENDING` keywords in grammar and parser.
  - Implemented arbitrary expression evaluation in `ORDER BY` with `WITH` aliasing scope tracking.
  - Implemented `percentileDisc` and `percentileCont` discrete and continuous percentile functions.
- **Phase B (Mutations & Semantic Rigor)**:
  - Label synchronization and label index cleanup on `REMOVE` and `DELETE`.
  - Nested map/list expression and `Path` deletion in `DELETE`.
  - Non-null validation in `MERGE` patterns.
  - Variable-length relationship lists in pattern matching.
  - Integer division truncation (`/`) on integer operands.
- **Phase C (Compile-Time Validation & Types)**:
  - Created `gql_core/query/static_types.py` for static type checking: boolean expressions, quantifier constraints, property access on non-maps, pattern expressions, and procedure calls.
  - Added dedicated error classes in `gql_core/errors.py`: `EntityNotFoundError`, `ConstraintVerificationError`, `ProcedureError`, `ParameterMissingError`, `ArgumentError`.
- **Phase D (Temporal & Duration Engine)**:
  - Created `gql_core/query/cypher_temporal.py` supporting full openCypher temporal types (`Date`, `Time`, `LocalTime`, `DateTime`, `LocalDateTime`, `Duration`).
  - Added support for ISO-8601 parsing, component extraction, date/time constructors, duration arithmetic, and truncation.

---

## 5. Verification Suite Summary

- **Unit, Regression & Harness Integrity Tests (`pytest tests/`)**: **341 / 341 passed (100%) in 25.84s**, including all 12 counterexample tests in `tests/test_tck_harness_integrity.py`.
- **Official LDBC SNB SF0.1 Benchmark (`python -m benchmark.snb.runner`)**: **4 / 4 official operations** (`IS1_p1`, `IS1_p2`, `IS3_p1`, `IS3_p2`) and **7 / 7 total queries** achieved `VERIFIED_EXACT_MATCH` against the independent SQLite Answer Oracle on 327,588 nodes and 1,477,965 edges.
- **Wheel & sdist Packaging (`python -m build`)**: Both `gql_core-0.2.0a1.tar.gz` and `gql_core-0.2.0a1-py3-none-any.whl` built cleanly with validated metadata, entry points, and version `0.2.0a1`.
