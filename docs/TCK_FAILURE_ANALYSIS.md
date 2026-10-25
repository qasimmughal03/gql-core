# openCypher TCK Failure Analysis & Harness Integrity Audit

**Scope**: 3,897 Concrete Upstream Scenarios (1,339 Regular `Scenario:` + 2,558 `Scenario Outline:` expansions across 220 `.feature` files, openCypher TCK 2024.3)  
**Source of Truth**: `benchmark/results/tck_compatibility_results.json`  
**Base Commit Audited**: `94c57f219f085a997031baa5452bfe1a220cac94`  
**Final Release Commit**: `67648c5`

---

## 1. Before / Audit-Exposed / Final Remediated Classification Matrix

| Metric | Prior Report (`94c57f2` Permissive Harness) | Audit-Exposed Strict Gate | Final Remediated Strict Gate (`67648c5`) |
|---|---|---|---|
| **Total Scenarios** | 1,339 | 3,897 | **3,897** |
| **Supported Scenarios** | 1,321 | 3,879 | **3,879 (99.54%)** |
| **Passed Result Checks (`PASS_RESULT`)** | 1,176 | 2,130 | **3,187 (100.00%)** |
| **Passed Expected-Error Checks (`PASS_EXPECTED_ERROR`)** | 145 | 315 | **692 (100.00%)** |
| **Passed Mutation Side-Effect Checks** | 0 (Unchecked) | 222 (Unchecked pass: 2,130) | **250 (Full SE pass: 3,187)** |
| **Failed Results (`FAIL_WRONG_RESULT`)** | 0 | 980 | **0** |
| **Failed Compile (`FAIL_COMPILE`)** | 0 | 408 | **0** |
| **Failed Runtime (`FAIL_RUNTIME`)** | 0 | 46 | **0** |
| **Wrong Error Categories / Phases** | 0 (Unchecked) | 45 | **0** |
| **Blocked / Uninterpreted (`BLOCKED`)** | 0 | 0 | **0** |
| **Unsupported (`UNSUPPORTED`)** | 18 | 18 | **18 (Documented)** |
| **Supported Pass Rate (Full Expanded)** | 100.00% (claimed) | 63.03% (2,445 / 3,879) | **100.00% (3,879 / 3,879)** |
| **Supported Pass Rate (Non-Outline)** | 100.00% (claimed) | 95.31% (1,259 / 1,321) | **100.00% (1,321 / 1,321)** |

---

## 2. Category Breakdown (Final Remediated Strict Harness — Full 3,897 Expanded Corpus)

All numbers generated directly from `benchmark/results/tck_compatibility_results.json`:

| TCK Category | Total Scenarios | `PASS_RESULT` | `PASS_EXPECTED_ERROR` | `FAIL_WRONG_RESULT` | `FAIL_COMPILE` | `FAIL_RUNTIME` | `BLOCKED` | `UNSUPPORTED` |
|---|---|---|---|---|---|---|---|---|
| **clauses** | 1,251 | 847 | 400 | 0 | 0 | 0 | 0 | 4 |
| **expressions** | 2,616 | 2,312 | 292 | 0 | 0 | 0 | 0 | 12 |
| **useCases** | 30 | 28 | 0 | 0 | 0 | 0 | 0 | 2 |
| **Total** | **3,897** | **3,187** | **692** | **0** | **0** | **0** | **0** | **18** |

---

## 3. Root-Cause Remediation Inventory

### 3.1 Mutation Side-Effect Remediation (Phase B)
1. **Primary Label Synchronization on Node Label Removal**:
   - Updated `_execute_remove_clause` so that removing a node's primary or last label resets `node.label` to `"Node"` and purges `graph._by_label[lbl]`.
2. **Deleting Paths and Nested Collection Expressions**:
   - Extended `_execute_delete_clause` to delete relationship elements before node elements for `Path` instances (`DETACH DELETE p`), resolving path variables and nested map/list indexing (`DELETE rels.key.key[0]`).
3. **`MERGE` Index Purging & Read-Own-Writes**:
   - `PropertyGraph.delete_node` now comprehensively disposes of all node entries across every label bucket in `self._by_label`.
   - `_execute_merge_clause` enforces non-null property assertions in `MERGE` patterns, raising `SemanticError` (`MergeReadOwnWrites`) when null property values are bound.

### 3.2 Error Categories and Execution Phases (Phase C)
1. **Compile-Time Static Validation (`gql_core/query/static_types.py`)**:
   - Pre-execution validation catches invalid types in boolean expressions (`NOT 1`, `'true' AND true`), non-map property access (`1.prop`), invalid quantifier collections, invalid pattern variable rebindings, and procedure call signatures (`validate_call_static`).
2. **Domain-Specific Error Classes (`gql_core/errors.py`)**:
   - Introduced explicit error classes inheriting properly from standard exceptions:
     - `EntityNotFoundError` for accessing deleted entities (`Return2#15`, `Return2#17`).
     - `ConstraintVerificationError` for constraint violations like deleting nodes with active relationships (`Delete1#7`).
     - `ProcedureError`, `ParameterMissingError`, and `ArgumentError` for runtime procedure and parameter checks.
3. **Phase Separation in Harness**:
   - `_execute_query_with_phase()` strictly distinguishes `compile_time` (`parse` + `validate_query`) from `runtime` (`execute` / `execute_pipeline`), matching upstream TCK expectations.

### 3.3 Exact Result & Type Semantics (Phase A & B)
1. **`Match4#1`**: Bound variable-length relationship variables `r` in `MATCH (a)-[r*]->(b)` as `list[Edge]`.
2. **Integer Division**: Enforced integer division semantics in `Arithmetic` and `_eval_expr_with_aggs` so that `/` on integer operands yields integer results truncating towards zero.
3. **Keyword Expansion**: Supported `ASCENDING` and `DESCENDING` keywords in grammar and parser.
4. **Ordering & Aggregations**: Implemented general expression evaluation in `ORDER BY` with `WITH` alias scope tracking, and implemented `percentileDisc` / `percentileCont`.

### 3.4 Temporal & Duration Engine (Phase D)
1. Created `gql_core/query/cypher_temporal.py` implementing all openCypher temporal types (`Date`, `Time`, `LocalTime`, `DateTime`, `LocalDateTime`, and `Duration`).
2. Implemented ISO-8601 string parsing, component extraction (`year`, `month`, `day`, `hour`, `minute`, `second`, etc.), duration arithmetic, duration functions (`between`, `inMonths`, `inDays`, `inSeconds`), and truncation functions.
