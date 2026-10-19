# openCypher TCK Failure Analysis & Harness Integrity Audit

**Scope**: 3,897 Concrete Upstream Scenarios (1,339 Regular `Scenario:` + 2,558 `Scenario Outline:` expansions across 220 `.feature` files, openCypher TCK 2024.3)  
**Source of Truth**: `benchmark/results/tck_compatibility_results.json`  
**Base Commit Audited**: `94c57f219f085a997031baa5452bfe1a220cac94`

---

## 1. Before / After Classification Matrix

| Metric | Prior Report (`94c57f2` Permissive Harness) | Strict Harness — Non-Outline Corpus (1,339) | Strict Harness — Full Expanded Corpus (3,897) |
|---|---|---|---|
| **Total Scenarios** | 1,339 | **1,339** | **3,897** |
| **Supported Scenarios** | 1,321 | **1,321** | **3,879** |
| **Passed Result Checks (`PASS_RESULT`)** | 1,176 | **1,147** | **2,130** |
| **Passed Expected-Error Checks (`PASS_EXPECTED_ERROR`)** | 145 | **112** | **315** |
| **Passed Mutation Side-Effect Checks** | 0 (Unchecked) | **219** (1,147 total SE checks) | **222** (2,130 total SE checks) |
| **Failed Results (`FAIL_WRONG_RESULT`)** | 0 | **19** (13 side-effect + 6 value/type) | **980** (13 side-effect + 967 value/type/no-err) |
| **Failed Compile (`FAIL_COMPILE`)** | 0 | **3** | **408** |
| **Failed Runtime (`FAIL_RUNTIME`)** | 0 | **40** | **46** |
| **Wrong Error Categories / Phases** | 0 (Unchecked) | **33** | **45** |
| **Blocked / Uninterpreted (`BLOCKED`)** | 0 | **0** | **0** |
| **Unsupported (`UNSUPPORTED`)** | 18 | **18** | **18** |
| **Supported Pass Rate** | 100.00% (claimed) | **95.31% (1,259 / 1,321)** | **63.03% (2,445 / 3,879)** |

---

## 2. Category Breakdown (Strict Harness — Full 3,897 Expanded Corpus)

| TCK Category | Total Scenarios | `PASS_RESULT` | `PASS_EXPECTED_ERROR` | `FAIL_WRONG_RESULT` | `FAIL_COMPILE` | `FAIL_RUNTIME` | `BLOCKED` | `UNSUPPORTED` |
|---|---|---|---|---|---|---|---|---|
| **clauses** | 1,251 | 749 | 236 | 168 | 58 | 36 | 0 | 4 |
| **expressions** | 2,616 | 1,353 | 79 | 812 | 350 | 10 | 0 | 12 |
| **useCases** | 30 | 28 | 0 | 0 | 0 | 0 | 0 | 2 |
| **Total** | **3,897** | **2,130** | **315** | **980** | **408** | **46** | **0** | **18** |

---

## 3. Root-Cause Inventory of Failures Exposed by the Strict Harness

### 3.1 Mutation Side-Effect Failures (13 Scenarios)
1. **Stale Primary Label on Single-Label Removal (`Remove2#1`, `Remove3#8..14` — 8 scenarios)**:
   - `_execute_remove_clause` removes the label from `node.labels` and `graph._by_label`, but leaves `node.label` populated with the removed label name.
2. **Deleting Path Values and Nested Map/List Expressions (`Delete3#1`, `Delete5#6`, `Delete5#7` — 3 scenarios)**:
   - `_execute_delete_clause` only deletes `Node` and `Edge` instances, failing to detach-delete `Path` objects (`Delete3#1`, `Delete5#7`) or resolve multi-level map/list indexing in `DELETE rels.key.key[0]` (`Delete5#6`).
3. **`MERGE` Matching Deleted Nodes in the Same Query (`Merge1#14`, `Merge5#20` — 2 scenarios)**:
   - `PropertyGraph.delete_node` removes the node from `self._nodes` but does not purge the node ID from `self._by_label`, causing `graph.nodes_by_label()` in a subsequent `MERGE` clause to match deleted nodes.

### 3.2 Wrong Error Categories and Phases (45 Scenarios: 33 Non-Outline + 12 Outline)
1. **Compile-Time Errors Raised at Runtime**:
   - Procedure signature/argument/yield validation (`Call1#7..10`, `Call1#15..16`, `Call2#4..6`, `Call5#5..6`) and `MERGE` bound-variable / var-length validation (`Merge5#22`, `Merge5#28`) are checked during `execute_pipeline` (`runtime`) instead of `validate_query` (`compile_time`).
   - Function argument type checks (`Graph3#8`, `Graph9#5..7`) raise `TypeError` at runtime instead of `SyntaxError: InvalidArgumentType` at compile time.
2. **Generic `RuntimeError` Instead of Domain Exception Classes**:
   - `Delete1#7` (`DeleteConnectedNode`) raises `RuntimeError` instead of `ConstraintVerificationError`.
   - `Return2#15..17` (`DeletedEntityAccess`) raise `RuntimeError` instead of `EntityNotFoundError`.
3. **Runtime Errors Raised at Compile Time**:
   - `Merge1#17` and `Merge5#29` (`MergeReadOwnWrites` on `MERGE ({num: null})`) raise `SemanticError` during `validate_query` (`compile_time`) instead of `runtime`.

### 3.3 Exact Result & Type Comparison Failures (6 Non-Outline Scenarios)
1. **`Match4#1`**: Variable-length edge variable `r` in `MATCH (a)-[r*]->(b)` returns a single `Edge` instead of a list `[Edge]` when routed through the non-pipeline planner.
2. **`Return6#16`**: Column projection naming mismatch.
3. **`WithOrderBy1#13`, `WithOrderBy1#16`**: `localtime` / `time` formatting appends `:00` when seconds are zero (`'10:35:00'` vs `'10:35'`).
4. **`Mathematical8#1`, `Mathematical8#2`**: Integer division inside arithmetic expressions produces `float` (`1.0`, `-15.0`) instead of `int` (`1`, `-15`).

### 3.4 `Scenario Outline:` Expansion Failures (1,372 Scenarios Across 2,558 Expanded Rows)
Previously skipped `Scenario Outline:` blocks in `Comparison1..2`, `Boolean1..4`, `List1..11`, `Null1..3`, `Quantifier1..8`, `Temporal1..10`, `WithOrderBy1..3`, and `Match1..6` are now fully expanded and evaluated, exposing 961 wrong-result/missing-error cases, 405 compile failures, and 6 runtime failures across parameterized expression and type-coercion edge cases.
