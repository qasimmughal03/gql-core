# GQL-Core Operator & Composition Test Matrix

**Version**: 1.0  
**Test Suite**: 303 / 303 tests passing (100%)  
**Audit Date**: 2026-10-18  

---

## 1. Overview

This matrix documents the verification coverage for all operator categories, required compositions, edge cases, and inference rules required by the mission specification.

---

## 2. Required Compositions Matrix

| Required Composition | Test Location | Test Function | Status |
| :--- | :--- | :--- | :---: |
| `AND(EXISTS, EXISTS)` | `tests/test_boolean_and_quantifiers.py` | `test_and_exists_and_not_exists` | **PASS** |
| `AND(EXISTS, NOT_EXISTS)` | `tests/test_boolean_and_quantifiers.py` | `test_and_exists_and_not_exists` | **PASS** |
| `OR(EXISTS, EXISTS)` | `tests/test_boolean_and_quantifiers.py` | `test_nested_boolean_composition_graph_predicates` | **PASS** |
| `NOT(OR(...))` | `tests/test_boolean_and_quantifiers.py` | `test_three_valued_logic_truth_tables` | **PASS** |
| `AND(OR(...), NOT_EXISTS(...))` | `tests/test_boolean_and_quantifiers.py` | `test_nested_boolean_composition_graph_predicates` | **PASS** |
| `AT_LEAST(N, relation predicate)` | `tests/test_boolean_and_quantifiers.py` | `test_quantified_relationship_reasoning` | **PASS** |
| `ALL(related entities, predicate)` | `tests/test_boolean_and_quantifiers.py` | `test_quantified_relationship_reasoning` | **PASS** |
| `NONE(related entities, predicate)` | `tests/test_boolean_and_quantifiers.py` | `test_quantified_relationship_reasoning` | **PASS** |
| `SINGLE(related entities, predicate)` | `tests/test_boolean_and_quantifiers.py` | `test_quantified_relationship_reasoning` | **PASS** |
| `EXISTS(MULTI_HOP(...))` | `tests/test_audit_regressions.py` | `test_diamond_graph_exact_two_hops` | **PASS** |
| `NOT_EXISTS(CORRELATED_SUBQUERY(...))`| `tests/test_boolean_and_quantifiers.py` | `test_correlated_subquery_in_exists` | **PASS** |
| `GROUP_BY + COUNT + HAVING` | `tests/test_relational_and_set_algebra.py` | `test_group_by_aggregates_and_having` | **PASS** |
| `OPTIONAL_MATCH + COALESCE` | `tests/test_relational_and_set_algebra.py` | `test_optional_match_left_outer_join` & `test_case_when_and_coalesce` | **PASS** |
| `UNION + DISTINCT` | `tests/test_relational_and_set_algebra.py` | `test_set_algebra_union_intersect_except` | **PASS** |
| `INTERSECT + EXCEPT` | `tests/test_relational_and_set_algebra.py` | `test_set_algebra_union_intersect_except` | **PASS** |
| `TYPE_INFERENCE + EXISTS` | `tests/test_ontology_and_inference.py` | `test_ontology_subtype_hierarchy_and_validation` | **PASS** |
| `INVERSE + TRANSITIVE_CLOSURE` | `tests/test_ontology_and_inference.py` | `test_inference_inverse_symmetric_transitive_rules` | **PASS** |
| `TEMPORAL_FILTER + RELATIONSHIP_FILTER`| `tests/test_temporal_and_collections.py` | `test_temporal_filter_in_evaluation` | **PASS** |
| `OPEN_WORLD + NEGATION` | `tests/test_ontology_and_inference.py` | `test_closed_world_vs_open_world_negation` | **PASS** |
| `CLOSED_WORLD + NEGATION` | `tests/test_ontology_and_inference.py` | `test_closed_world_vs_open_world_negation` | **PASS** |

---

## 3. Operator Boundary & Edge Case Coverage

| Category | Boundary Condition | Verified Behavior |
| :--- | :--- | :--- |
| **Empty Graph** | Executing Scan or Expand on graph with 0 nodes/edges. | Returns `[]` without error. |
| **Empty Collection** | Evaluating `ALL` on empty related set. | Evaluates to `True` (vacuous truth). |
| **Empty Collection** | Evaluating `ANY` on empty related set. | Evaluates to `False`. |
| **Duplicate Rows** | `UNION ALL` with duplicate records. | Retains duplicate rows with exact multiplicity. |
| **Set Deduplication** | `UNION` / `DISTINCT` on duplicates. | Deduplicates rows using normalized hash keys. |
| **Null Comparisons** | Equality, inequality, ordered comparisons against `None`. | Evaluates to `None` (Unknown) under 3VL. |
| **Missing Property** | Accessing unasserted property on Node or Edge. | Returns `None` without raising `KeyError`. |
| **Record ID 0 / False** | Storing integer `0` or boolean `False` as ID or property. | Preserved as valid distinct value, not treated as absent/falsy. |
| **Incompatible Types** | Comparing boolean with non-boolean. | Evaluates deterministically to `False` (`=`) or `True` (`!=`). |
| **Invalid Scope** | Query referencing unbound variable. | Rejected by `validate_logical_plan` with `UNBOUND_VARIABLE`. |
| **Cyclic Traversal** | Directed cycles `A -> B -> C -> A`. | Cycle-bounded by openCypher trail semantics (no repeated edges). |
| **Parallel Edges** | Multiple edges between identical endpoints. | Retained as distinct paths and bindings. |
| **Inference Deduplication** | Relationship both asserted and inferred. | Inferred edge creation skipped; no double-counting. |
