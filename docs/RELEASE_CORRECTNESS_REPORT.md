# GQL-Core Release Correctness Report (Independent TCK Harness Integrity Gate)

**Release Target**: `0.2.0a1`  
**Date**: October 19, 2026  
**Auditor**: Principal Database & Verification Harness Engineering  
**Branch**: `feat/implementation`  
**Base Commit**: `94c57f219f085a997031baa5452bfe1a220cac94`  
**Repository**: `qasimmughal03/knowledge-graoh-with-formal-query`  
**Source of Truth**: `benchmark/results/tck_compatibility_results.json`, `benchmark/results/snb_interactive_results.json`

---

## 1. Executive Summary & Release Gate Verdict

An independent TCK verification harness audit was executed starting from commit `94c57f219f085a997031baa5452bfe1a220cac94`. In accordance with the Harness Integrity Gate rules:
- **Zero new query-language features were added** during this gate.
- **No expected results were altered, no comparisons were weakened, and no unsupported classifications were expanded.**
- Every false-positive path identified in `benchmark/tck/gherkin_parser.py` and `benchmark/tck/tck_adapter.py` was eliminated and locked down with 12 counterexample unit tests in `tests/test_tck_harness_integrity.py`.

### Release Gate Verdict: **NOT APPROVED FOR RELEASE (HOLD — Engine Defects Exposed by Strict Harness)**

Per the gate rule (*"The release is approved only when all declared supported upstream assertions are genuinely checked and pass"*):
- When the TCK verification harness enforces **strict mutation side effects**, **strict error categories and phases (`compile_time` vs `runtime`)**, **exact entity/list/numeric result comparisons**, and **full `Scenario Outline` expansion**, the engine passes **1,259 / 1,321 (95.31%)** of the non-outline scenarios (down from the previously claimed 1,321 / 1,321) and **2,445 / 3,879 (63.03%)** of the full expanded corpus (including all 2,558 `Scenario Outline` rows that were previously skipped).

---

## 2. False-Positive Paths Eliminated in the Verification Harness

1. **Mutation Side-Effect Verification (`And the side effects should be:` & `And no side effects`)**:
   - Extended `benchmark/tck/gherkin_parser.py` to parse `And no side effects` and all 8 TCK side-effect counters (`+nodes`, `-nodes`, `+relationships`, `-relationships`, `+labels`, `-labels`, `+properties`, `-properties`).
   - Added `_snapshot_graph()` and `_compute_side_effects()` in `benchmark/tck/tck_adapter.py` to record graph state immediately after fixture setup and immediately after the query under test (before any `control_query`).
   - Separated `control_query` result assertions (`control_expected_kind`, `control_expected_rows`, `control_in_order`, `control_ignore_list_order`) from primary query result assertions so both the primary query and the control query are verified independently.
   - Verified `Create1.feature` and `Delete1.feature` against upstream definitions and added counterexample unit tests proving a no-op `CREATE` or no-op `DELETE` fails `Create1#1` and `Delete1#1`.

2. **Expected-Error Category and Phase Enforcement**:
   - Replaced the permissive `_is_matching_error()` check (which previously matched `"Error" in type(exc).__name__`) with `_EXPLICIT_ERROR_CATEGORY_MAP` covering `SyntaxError`, `SemanticError`, `TypeError`, `ArgumentError`, `EntityNotFound`, `ConstraintVerificationFailed`, `ProcedureError`, and `ParameterMissing`.
   - Separated query execution into `compile_time` (`parse` + `validate_query`) and `runtime` (`execute` / `execute_pipeline`) via `_execute_query_with_phase()`, verifying that `at compile time` errors occur during compilation and `at runtime` errors occur during execution.
   - Isolated fixture setup (`_load_named_graph`, `background_create`, `scenario_create`) before expected-error testing so any fixture exception produces `BLOCKED`, never `PASS_EXPECTED_ERROR`.

3. **Exact Result Semantics**:
   - **Ordered Lists**: Removed unconditional fallback to unordered multiset matching for lists; list element order is now strictly enforced unless the Gherkin step explicitly specifies `(ignoring element order for lists)`.
   - **Exact Nodes & Relationships**: Replaced subset property matching with exact label-set and exact property-map comparison (`_compare_maps_strict`), rejecting entities with unexpected extra properties.
   - **Exact Paths**: Added `ExpectedPath` parsing and verification of node sequences, relationship sequences, and per-hop directions (`->`, `<-`, `--`).
   - **Numeric & String Strictness**: Enforced `int` vs. `float` type distinction (`1 != 1.0`), `bool` isolation, `NaN` and `+/-Infinity` sign checks, exact column name matching (`dict.keys(actual_row)` bypassing `Row` lenient lookup), and removed diagnostic ISO time regex normalization.

4. **Full Gherkin Grammar & `Scenario Outline:` Expansion**:
   - Removed the `Scenario Outline:` skip in `gherkin_parser.py` and implemented full `Examples:` table placeholder substitution (`<param>`) across queries, control queries, fixtures, parameters, procedure tables, expected result tables, and side effects, expanding the corpus from 1,339 regular scenarios to **3,897 total concrete scenarios** (1,339 regular + 2,558 outline expansions).
   - Added `parse_errors` tracking so any unrecognized Gherkin step or assertion modifier immediately marks the scenario `BLOCKED` rather than being silently ignored.

---

## 3. Before / After TCK Verification Results

All numbers below are generated directly from `benchmark/results/tck_compatibility_results.json`:

| Metric | Before (`94c57f2` Permissive Harness) | After (1,339 Regular Scenarios — Strict Harness) | After (Full 3,897 Expanded Corpus — Strict Harness) |
|---|---|---|---|
| **Total Scenarios** | 1,339 (Outlines skipped) | **1,339** | **3,897** (1,339 Regular + 2,558 Outline rows) |
| **Supported Scenarios** | 1,321 | **1,321** (98.66%) | **3,879** (99.54%) |
| **Unsupported Scenarios (`UNSUPPORTED`)** | 18 | **18** | **18** |
| **Blocked / Uninterpreted (`BLOCKED`)** | 0 | **0** | **0** |
| **Passed Result Checks (`PASS_RESULT`)** | 1,176 (claimed) | **1,147** (97.53% of 1,176) | **2,130** (66.83% of 3,187) |
| **Passed Expected-Error Checks (`PASS_EXPECTED_ERROR`)** | 145 (claimed) | **112** (77.24% of 145) | **315** (45.52% of 692) |
| **Passed Mutation Side-Effect Checks** | 0 (Unchecked) | **219** (1,147 total SE checks passed) | **222** (2,130 total SE checks passed) |
| **Failed Results (`FAIL_WRONG_RESULT`)** | 0 (claimed) | **19** (13 side-effect + 6 value/type) | **980** (13 side-effect + 967 value/type/no-err) |
| **Failed Compile (`FAIL_COMPILE`)** | 0 (claimed) | **3** | **408** |
| **Failed Runtime (`FAIL_RUNTIME`)** | 0 (claimed) | **40** | **46** |
| **Wrong Error Categories / Phases** | 0 (Unchecked) | **33** | **45** |
| **Supported Pass Rate** | 100.00% (claimed) | **95.31% (1,259 / 1,321)** | **63.03% (2,445 / 3,879)** |

---

## 4. Breakdown of Exposed Engine Defects (Non-Outline 1,339 Corpus: 62 Failures)

### 4.1 Failed Mutation Side-Effect Checks (13 Scenarios)
- **Label removal on single-label nodes (`Remove2#1`, `Remove3#8..14` — 8 scenarios)**: Removing the last label from a node (`REMOVE n:L`) clears `node.labels` to `()`, but leaves `node.label = 'L'` unchanged on the `Node` object, so the label remains active in the graph (`actual_se = {}` instead of `{'-labels': 1}`).
- **Deleting Paths and nested Map/List entities (`Delete3#1`, `Delete5#6`, `Delete5#7` — 3 scenarios)**: `_execute_delete_clause` only handles `Node` and `Edge` instances, ignoring `Path` instances (`DETACH DELETE p`) and nested map/list index expressions (`DELETE rels.key.key[0]`).
- **`MERGE` matching nodes deleted earlier in the same query (`Merge1#14`, `Merge5#20` — 2 scenarios)**: `graph.delete_node()` removes nodes from `graph._nodes` but leaves stale node IDs in `graph._by_label[label]`, allowing subsequent `MERGE (a2:A)` in the same query to match deleted nodes.

### 4.2 Failed Exact Result / Type Checks (6 Scenarios)
- **`Match4#1`**: Variable-length relationship variable `r` in simple planner path returns a single `Edge` instead of `list[Edge]`.
- **`Return6#16`**: Unaliased expression column projection mismatch.
- **`WithOrderBy1#13`, `WithOrderBy1#16`**: Time string formatting includes `:00` seconds (`'10:35:00'` vs expected `'10:35'`), previously hidden by the `:00` regex hack in `tck_adapter.py`.
- **`Mathematical8#1`, `Mathematical8#2`**: Integer division / precedence expression returns `float` (`1.0`, `-15.0`) instead of `int` (`1`, `-15`), previously hidden by `int`/`float` coercion in `tck_adapter.py`.

### 4.3 Failed Expected-Error Category / Phase Checks (33 Scenarios) + Unraised Errors (10 Scenarios)
- **Compile-time errors raised at runtime (20 scenarios)**: `Call1#7..10`, `Call1#15..16`, `Call2#4..6`, `Call5#5..6`, `Merge5#22`, `Merge5#28`, `Graph3#8`, `Graph9#5..7`, etc. perform validation inside `executor.py` at runtime rather than in `semantic.py` at compile time.
- **Wrong exception category raised (9 scenarios)**:
  - `Delete1#7` raises generic `RuntimeError` instead of `ConstraintVerificationError` (`ConstraintVerificationFailed`).
  - `Return2#15..17` raise generic `RuntimeError` instead of `EntityNotFoundError` (`EntityNotFound`).
  - `Call1#11` raises `SemanticError` at runtime instead of `ParameterMissingError` at compile time.
  - `Call1#13..14` raise `SemanticError` at runtime instead of `ProcedureError` at compile time.
  - `Aggregation6#5` raises `SyntaxError` (`UnknownFunction: percentileDisc`) at compile time instead of `ArgumentError` at runtime.
- **Runtime error raised at compile time (2 scenarios)**: `Merge1#17` and `Merge5#29` (`MergeReadOwnWrites`) raise `SemanticError` at compile time instead of `runtime`.

---

## 5. Additional Verification Suites

- **Unit, Regression & Harness Integrity Tests (`pytest tests/`)**: **337 / 337 passed (100%)**, including all 12 new counterexample tests in `tests/test_tck_harness_integrity.py`.
- **Official LDBC SNB SF0.1 Benchmark (`python -m benchmark.snb.runner`)**: **4 / 4 official operations** (`IS1_p1`, `IS1_p2`, `IS3_p1`, `IS3_p2`) and **7 / 7 total queries** achieved `VERIFIED_EXACT_MATCH` against the independent SQLite Answer Oracle on 327,588 nodes and 1,477,965 edges.
- **Wheel & sdist Packaging (`python -m build`)**: Both `gql_core-0.2.0a1.tar.gz` and `gql_core-0.2.0a1-py3-none-any.whl` built cleanly and verified metadata, entry points, and version `0.2.0a1`.
