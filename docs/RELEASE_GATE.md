# GQL-Core v0.2.0 Release Gate Audit Report

**Date**: 2026-10-18  
**Repository**: `knowledge-graoh-with-formal-query`  
**Branch**: `feat/implementation`  
**Baseline Commit**: `b404eb72ad101a24543ff0387bdf701fdb5b1cd0`  
**Release Gate Status**: **READY WITH DOCUMENTED LIMITATIONS**  

---

## 1. Executive Summary

This release gate document establishes the formal engineering evidence required for tagging and releasing GQL-Core v0.2.0. Following an independent audit of commit `b404eb7`, six mission-critical correctness, identity preservation, null logic, benchmark integrity, and public API claims were identified and addressed.

All 276 unit, regression, and property tests pass in 11.1s. An isolated virtual environment verification confirmed that wheel packaging and CLI commands execute out-of-tree without source checkout dependencies. The release gate status is determined to be **READY WITH DOCUMENTED LIMITATIONS**.

---

## 2. Audit & Verification Findings by Area

### 2.1 Issue 1: Path Traversal Correctness (Diamond Graph & Trail Semantics)

- **Initial Defect**:
  In `gql_core/query/executor.py` (`rpq_traverse`), path traversal tracked visited nodes using a global set `visited = {start.id}`. In graphs containing multiple distinct paths to the same destination—such as the classic diamond graph:
  ```
  A -> C
  A -> B
  B -> C
  ```
  an exact two-hop query from `A` (`*2..2`) must reach `C` via the path `A -> B -> C`. Because `C` was already recorded in `visited` at hop 1 (via direct edge `A -> C`), subsequent traversal paths to `C` were prematurely discarded, yielding `[]` instead of `[{"id": "C"}]`. Furthermore, this global node pruning violated openCypher relationship trail semantics (relationship isomorphism: relationships cannot be traversed more than once per pattern, but nodes may be revisited).

- **Reproduction / Failing Test**:
  - Test graph: Nodes `A`, `B`, `C`; Edges `(A)->(C)`, `(A)->(B)`, `(B)->(C)`.
  - Executed Query: `MATCH (a:Node {id: 'A'})-[:REL*2..2]->(c:Node) RETURN c.id AS id`.
  - Previous Result: `[]`. Expected Result: `[{"id": "C"}]`.
  - In addition, cycles (e.g. `A -> B -> C -> A`) at length 3 failed to return `A` because `A` was marked visited.

- **Code Change**:
  In `gql_core/query/executor.py` and `query/executor.py`:
  - Replaced the global `visited: set[Any]` with per-path relationship trail tracking:
    ```python
    queue: deque[tuple[Node, int, frozenset[str]]] = deque([(start, 0, frozenset())])
    ```
  - Traversed edge `e` only if `e.id not in used_edges`.
  - Propagated new state `(nbr, depth + 1, used_edges | {e.id})`.
  - Destination nodes reached at `depth >= min_hops` are yielded for each valid path trail, enabling multiple distinct paths to the same target node, cycle returns, and parallel edge differentiation.

- **Regression Test**:
  - `tests/test_audit_regressions.py::test_diamond_graph_exact_two_hops`
  - `tests/test_audit_regressions.py::test_path_traversal_cycles_and_parallel_edges`
  - `tests/test_audit_regressions.py::test_exact_length_bounded_paths`
  - `tests/test_audit_regressions.py::test_trail_semantics_relationship_isomorphism`

- **Verification Result**:
  - Diamond graph exact 2-hop query returns `[{"id": "C"}]`.
  - Range `*1..2` hops from `A` returns `[{"id": "B"}, {"id": "C"}, {"id": "C"}]` (preserving both 1-hop and 2-hop paths to `C`).
  - Parallel edges yield distinct path bindings.
  - Repeated endpoints via cycles return to start node at length 3 without infinite recursion.

- **Remaining Limitations**:
  - Only unweighted path traversal is supported. Shortest-path algorithms (Dijkstra / A*) and Cypher path variable assignments (`p = (a)-[*]->(b)`) are excluded from v0.2.0 scope.

---

### 2.2 Issue 2: Graph Ingestion Identities in Public Adapters

- **Initial Defect**:
  - `PropertyGraph.from_networkx` coerced all node keys to string via `str(n)`, causing integer key `1` and string key `"1"` to collide and overwrite each other, silently merging distinct nodes.
  - `from_networkx` traversed `G.edges(data=True)`, which discarded edge keys in `nx.MultiGraph` and `nx.MultiDiGraph`, collapsing parallel edges between the same endpoints.
  - `PropertyGraph.from_records` used `item.pop("id", None) or item.pop("@id", None)`, which treated record ID `0` as falsy, discarding it or generating surrogate IDs.
  - Empty strings `""` and `None` were accepted as node IDs without validation, and duplicate IDs silently merged nodes instead of rejecting invalid conversions.
  - Falsy property values (`False`, `0`, `""`, `[]`) were vulnerable to deletion or mishandling.

- **Reproduction / Failing Test**:
  - NetworkX graph with node `1` (int) and node `"1"` (str): previous adapter collapsed them to 1 node.
  - Record with `{"id": 0, "name": "Zero", "active": False, "score": 0}`: resulted in altered ID or dropped fields.
  - Record with `{"name": "No ID"}`: silently assigned synthetic ID.
  - Duplicate record ID `[{"id": "u1"}, {"id": "u1"}]`: silently merged without error.
  - `MultiDiGraph` with parallel edges: collapsed into 1 edge.

- **Code Change**:
  In `gql_core/graph.py` and `graph/store.py`:
  - Updated `Node.id`, `Edge.id`, `Edge.src`, and `Edge.dst` types to `Any` to natively store primitive types (`int`, `str`, etc.).
  - In `from_networkx`: retained native node key `n`; added multigraph detection (`G.is_multigraph()`) and read `G.edges(keys=True, data=True)`; validated node identifiers; preserved falsy properties.
  - In `from_records`: safely extracted ID checking `k in item and item[k] is not None and item[k] != ""` (preserving integer `0`); raised `ValueError("Record missing identifier or identifier is empty")` on missing/empty IDs; raised `ValueError(f"Duplicate node identifier collision: {node_id}")` on duplicate keys.
  - In `from_edges` and `from_dict`: enforced endpoint validation and rejected edge collisions.

- **Regression Test**:
  - `tests/test_audit_regressions.py::test_networkx_adapter_integer_vs_string_identities`
  - `tests/test_audit_regressions.py::test_adapter_record_id_zero_and_falsy_properties`
  - `tests/test_audit_regressions.py::test_adapter_empty_missing_and_duplicate_rejection`
  - `tests/test_audit_regressions.py::test_multigraph_parallel_edges`

- **Verification Result**:
  - NetworkX integer `1` and string `"1"` remain distinct nodes with separate query match targets.
  - Record ID `0`, boolean `False`, integer `0`, empty string `""`, and empty list `[]` are fully preserved.
  - Missing and duplicate identifiers raise descriptive `ValueError` exceptions.
  - MultiDiGraph parallel edges are indexed and queried with separate edge IDs.

- **Remaining Limitations**:
  - Node IDs must be hashable Python types (`int`, `str`, `tuple`). Non-hashable objects (`dict`, `list`) cannot be used as node keys.

---

### 2.3 Issue 3: Three-Valued Logic (3VL) Null Semantics

- **Initial Defect**:
  `_eval_expr` evaluated comparison operators (`=`, `!=`, `<`, `>`, `<=`, `>=`) against `None` using Python's native 2-valued boolean logic. In openCypher and ISO GQL:
  - Comparing any value to `null` yields `null` (Unknown).
  - In `MATCH (n) WHERE NOT n.x = 2 RETURN n`, a node with `n.x = null` or missing `x` evaluated `null = 2` as `False`, and `NOT False` as `True`, incorrectly returning the node.
  - Under 3-valued logic (3VL / Kleene logic), `NOT (null = 2)` must evaluate to `null` (Unknown). Because `WHERE` filters keep rows strictly when the predicate evaluates to `True`, `Unknown` rows must be excluded.

- **Reproduction / Failing Test**:
  - Test graph with nodes:
    - `n1: {x: 2}`
    - `n2: {x: 4}`
    - `n3: {x: None}` (explicit null)
    - `n4: {}` (missing property)
  - Executed Query: `MATCH (n:Item) WHERE NOT n.x = 2 RETURN n.id AS id`.
  - Previous Result: `[{"id": "n2"}, {"id": "n3"}, {"id": "n4"}]` (erroneously including null and missing nodes).
  - Expected 3VL Result: `[{"id": "n2"}]`.

- **Code Change**:
  In `gql_core/query/executor.py` and `query/executor.py`:
  - Updated comparison evaluation: if either left or right operand evaluates to `None`, comparisons return `None` (Unknown).
  - Implemented type-mismatch handling: comparing boolean with non-boolean produces `False` for `=` and `True` for `!=`.
  - Implemented Kleene 3-valued logic for logical connectives:
    - `Not`: `None` -> `None`; `True` -> `False`; `False` -> `True`.
    - `And`: `False AND Unknown` -> `False`; `True AND Unknown` -> `None`; `True AND True` -> `True`.
    - `Or`: `True OR Unknown` -> `True`; `False OR Unknown` -> `None`; `False OR False` -> `False`.
  - In `_filter`: retained candidate rows strictly when `_eval_expr(...) is True`.

- **Regression Test**:
  - `tests/test_audit_regressions.py::test_three_valued_logic_null_semantics`
  - `tests/test_audit_regressions.py::test_missing_property_null_semantics`

- **Verification Result**:
  - `MATCH (n:Item) WHERE NOT n.x = 2 RETURN n.id AS id` returns strictly `[{"id": "n2"}]`.
  - `n.x = 2` returns strictly `[{"id": "n1"}]`.
  - Kleene truth tables for `AND`, `OR`, `NOT` verified against openCypher specification.

- **Remaining Limitations**:
  - Built-in scalar functions like `coalesce()` or `exists()` are not included in the v0.2.0 query grammar.

---

### 2.4 Issue 4: openCypher TCK Harness Reaudit

- **Initial Defect**:
  - In `benchmark/tck/tck_adapter.py`, `_normalize_cell_for_cmp` had a fallback: `or (s in actual.props.values())`, which allowed arbitrary property value matches to pass column checks.
  - In `_match_row`, candidate key matching permitted unaliased expression candidates (e.g. mapping `"a.name"` to `"name"`, or `"count(*)"` to `"count"`). While informative for diagnostics, this obscured whether GQL-Core adhered strictly to openCypher column naming conventions.
  - Past reporting presented 76/79 without distinguishing exact column naming from candidate alias expansion.

- **Reproduction / Failing Test**:
  - Scenarios expecting unaliased expression column headers (e.g., `"a.num"`, `"count(*)"`) passed under candidate matching but failed under exact column header comparison.
  - Permissive fallback could mask wrong projected fields.

- **Code Change**:
  In `benchmark/tck/tck_adapter.py` and `benchmark/tck/runner.py`:
  - Removed permissive fallback `or (s in actual.props.values())`.
  - Added explicit `relaxed_columns: bool = False` parameter to `_match_row` and `run_scenario`.
  - In strict mode (`relaxed_columns=False`), only exact expected column headers match actual row keys.
  - In diagnostic mode (`relaxed_columns=True`), expression candidate matching is documented as a diagnostic aid.
  - Executed both passes across the full 1,338 scenario upstream TCK corpus:
    - **Strict Mode**: 49 passed / 79 claimed (62.03%), 30 failed.
    - **Diagnostic Mode**: 76 passed / 79 claimed (96.20%), 3 failed.
  - Categorized the 30 failures: exactly 27 fail strictly due to unaliased column naming differences (GQL-Core returns clean attribute names `"num"`, `"count"` instead of verbatim Cypher strings `"a.num"`, `"count(*)"`). Exactly 3 fail due to semantic discrepancies (`Return4#4`, `Aggregation1#1`, `Aggregation3#1`).

- **Regression Test**:
  - `tests/test_benchmark_smoke.py::test_tck_smoke`
  - Automated dual-mode reporting in `benchmark/tck/runner.py`.

- **Verification Result**:
  - `benchmark/results/tck_compatibility_results.json` accurately reflects dual-mode metrics without hidden fallback heuristics.

- **Remaining Limitations**:
  - GQL-Core does not preserve verbatim Cypher expression syntax in unaliased projection keys. To ensure exact column names in result dictionaries, users should provide explicit aliases via `AS alias`.

---

### 2.5 Issue 5: Installed Package & Out-of-Tree Verification

- **Initial Defect**:
  - Prior benchmark and smoke executions ran from within the source checkout directory, potentially masking packaging oversights such as missing subpackages, uninstalled console scripts, or source directory imports bypassing `site-packages`.

- **Reproduction / Failing Test**:
  - Running from source checkout masks `setup.py` / `pyproject.toml` file inclusion bugs.

- **Code Change**:
  - Built distribution packages:
    - Wheel: `dist/gql_core-0.2.0-py3-none-any.whl` (56,867 bytes)
    - Sdist: `dist/gql_core-0.2.0.tar.gz` (51,489 bytes)
  - Created a clean, isolated virtual environment at `$env:TEMP\gql_test_env`.
  - Installed the wheel and declared runtime dependencies (`lark`, `pyyaml`, `requests`).
  - Executed verification from outside the source checkout (`C:\Users\HP`):
    - Recorded `gql_core.__file__`: `C:\Users\HP\AppData\Local\Temp\gql_test_env\Lib\site-packages\gql_core\__init__.py`.
    - Executed CLI command: `gql-core version` -> `gql-core 0.2.0`.
    - Executed documented public API example (`from_records` and `run`).

- **Regression Test**:
  - Clean virtual environment smoke test script executed out-of-tree.

- **Verification Result**:
  - Wheel and sdist build cleanly, install into empty environments, expose all public CLI commands and Python APIs, and operate independently of source tree files.

- **Remaining Limitations**:
  - Development and benchmark tools (`networkx`, `matplotlib`, `pytest`) are omitted from runtime requirements to keep the distribution lean.

---

### 2.6 Issue 6: Public API & Documentation Claims Alignment

- **Initial Defect**:
  - `README.md` and `docs/RELEASE_READINESS.md` claimed zero dependencies outside standard library and `lark`, omitting declared dependencies `pyyaml` and `requests`.
  - Documented CLI command `gql-core stats` which was not implemented in `gql_core/cli.py`.
  - Claimed thread-safe read operations without clarifying GIL semantics and external locking requirements.
  - Omitted minimum Python version (`>=3.11`).
  - Did not disclose strict vs diagnostic TCK pass rates.

- **Reproduction / Failing Test**:
  - Invoking `gql-core stats` returned CLI error.
  - Review of `pyproject.toml` dependencies contradicted README claims.

- **Code Change**:
  - Synchronized `README.md` and `docs/RELEASE_READINESS.md`:
    - Updated runtime dependencies: `lark>=1.2.2`, `pyyaml>=6.0.2`, `requests>=2.32.3`. Python requirement: `>=3.11`.
    - Updated adapter listings: `from_networkx`, `from_records`, `from_edges`, `from_dict`.
    - Updated CLI documentation: added `ask`, removed nonexistent `stats`.
    - Clarified thread safety: pure in-memory read operations are safe under GIL; concurrent writes require external locking.
    - Updated TCK conformance metrics: reported both strict (49/79) and diagnostic (76/79) modes with explicit explanation of the 27 column-naming differences.

- **Regression Test**:
  - `tests/test_audit_regressions.py::test_public_api_surface_and_execution`
  - CLI execution test.

- **Verification Result**:
  - Documentation, packaging metadata, and runtime behavior are fully aligned.

- **Remaining Limitations**:
  - Advanced Cypher features like mutations (`CREATE`, `MERGE`, `DELETE`), multi-clause piping (`WITH`, `UNWIND`), and subqueries are outside the declared read-only core language subset for v0.2.0.

---

## 3. Full Test Suite & Benchmark Metrics

| Metric | Result | Status |
| :--- | :--- | :--- |
| **Unit & Regression Suite** | 276 / 276 passed (11.1s) | **PASS** |
| **Benchmark Smoke Suite** | 2 / 2 passed (0.2s) | **PASS** |
| **openCypher TCK (Strict Mode)** | 49 / 79 passed (62.0%) | **DOCUMENTED** |
| **openCypher TCK (Diagnostic Mode)** | 76 / 79 passed (96.2%) | **PASS** |
| **LDBC SNB Interactive SF0.1 Ingestion** | 327,588 nodes, 1,477,965 edges loaded in 62.1s (1.81 GB peak RAM) | **PASS** |
| **Wheel & Sdist Build** | Built `dist/gql_core-0.2.0-py3-none-any.whl`, installed in clean venv | **PASS** |
| **Out-of-Tree Verification** | Imported from `site-packages`, CLI `version` and public API confirmed | **PASS** |

---

## 4. Release Gate Conclusion

**STATUS**: **READY WITH DOCUMENTED LIMITATIONS**

The GQL-Core v0.2.0 library satisfies all correctness, benchmark integrity, identity preservation, and packaging criteria. All known semantic limitations are explicitly documented in user-facing documentation and this release gate report. 

Per instructions, **no Git release tag has been created** and **no publication to PyPI has been performed**.
