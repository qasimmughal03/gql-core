# openCypher TCK Failure Analysis & Defect Inventory

**Scope**: 1,339 Upstream Scenarios (openCypher TCK pinned to 2024.3)  
**Evaluated Results**: 1,064 Passing (958 Results + 106 Errors), 133 Wrong Results, 133 Compile Failures, 9 Runtime Failures, 0 Blocked.  
**Author**: GQL-Core Database Compiler Engineering  

---

## 1. Architectural Classification of Mismatches

The 275 unpassed scenarios across the 1,339 TCK suite were analyzed and classified by their architectural root component:

```
┌────────────────────────────────────────────────────────┐
│                   TCK Corpus (1,339)                   │
├────────────────────────────────┬───────────────────────┤
│ Strict Passes (1,064 / 79.5%)  │ Non-Passes (275)      │
│  • PASS_RESULT: 958            │  • FAIL_COMPILE: 133  │
│  • PASS_EXPECTED_ERROR: 106    │  • FAIL_WRONG_RESULT: 133
│                                │  • FAIL_RUNTIME: 9    │
│                                │  • BLOCKED: 0         │
└────────────────────────────────┴───────────────────────┘
```

### Breakdown by Subsystem Component:

| Component Subsystem | Count | Root-Cause Category | Impacted Operations |
|---|---|---|---|
| **Parser / Grammar** | 71 | Missing Grammar Syntax | Multiple relationship types (`[:A\|B]`), ShortestPath functions, Subquery expressions (`CALL { ... }`), Map projection expressions (`n { .name, .age }`) |
| **Parser Lenience (Negative Tests)** | 42 | Under-constrained Syntax Rejection | Negative TCK tests expecting `syntax_error` on invalid syntax (e.g. deleting an int literal `DELETE 1`, naked labels) |
| **Physical Executor (Pattern Match)** | 29 | Pattern Cardinality & Multi-Label | Nodes with multiple concurrent labels (`MATCH (n:A:B)`), disconnected multi-pattern Cartesian products (`MATCH (a), (b)`) |
| **Physical Executor (Expressions)** | 62 | Extended Scalar Functions & Formatting | Path return objects (`relationships(p)`), dereferencing nested map expressions without alias, composite list arithmetic |
| **Physical Executor (Mutation Edges)** | 8 | Edge ID Collisions during Mutations | Re-using variable names across iterative CREATE/MERGE operations in `Create6` and `Merge8` |
| **Semantic Analyzer** | 63 | Scope & Binding Enforcement | Undefined variable checks in correlated WITH clauses, variable re-use across distinct MATCH clauses (`Match3#24-#28`) |

---

## 2. Detailed Root-Cause Investigations by Domain

### 2.1 Multi-Label Node Matching (`Match1#3`, `Match3#7`)
- **Component**: Physical Executor / `_match_path_pattern`
- **Minimal Reproducible Case**:
  - **Graph**:
    ```cypher
    CREATE (:A:B {id: 1}), (:A {id: 2}), (:B {id: 3})
    ```
  - **Query**:
    ```cypher
    MATCH (n:A:B) RETURN n.id AS id
    ```
  - **Expected**: `[{'id': 1}]` (only node 1 has both labels A and B)
  - **Actual**: `[{'id': 1}, {'id': 2}]` or row count mismatch
  - **Root Cause**: The current `NodePat` AST structure stores a single primary label `label: str | None`. When multiple labels are specified in Cypher (`:A:B`), the parser extracts the first label or combines them, failing to enforce intersection across the `_by_label` index sets.
  - **Remediation Target**: Extend `NodePat` to support `labels: tuple[str, ...]` and filter candidate node IDs using set intersection `set.intersection(*(graph._by_label[lbl] for lbl in node_pat.labels))`.

### 2.2 Disconnected Pattern Cartesian Products (`Match3#23`)
- **Component**: Physical Executor / Query Planner
- **Minimal Reproducible Case**:
  - **Graph**:
    ```cypher
    CREATE (:Person {name: 'Alice'}), (:Person {name: 'Bob'})
    CREATE (:City {name: 'London'}), (:City {name: 'Paris'})
    ```
  - **Query**:
    ```cypher
    MATCH (p:Person), (c:City) RETURN p.name, c.name
    ```
  - **Expected**: 4 rows (Alice-London, Alice-Paris, Bob-London, Bob-Paris)
  - **Actual**: 2 rows
  - **Root Cause**: Multi-pattern `MATCH` clauses sequentially chained into `_match_path_pattern` without taking the full Cartesian product across disconnected pattern components when variables do not overlap.

### 2.3 Multiple Relationship Types (`Union Rel Types`)
- **Component**: Grammar / Parser (`grammar.lark`)
- **Minimal Reproducible Case**:
  - **Query**:
    ```cypher
    MATCH (a)-[:KNOWS|FOLLOWS]->(b) RETURN b
    ```
  - **Expected**: Compile and match either `KNOWS` or `FOLLOWS` edge types.
  - **Actual**: `FAIL_COMPILE` (`LarkError: UnexpectedCharacters '|'`)
  - **Root Cause**: The current `rel_pat` rule in `grammar.lark` parses a single `label_name?`. Pipe-separated disjunction of relationship types (`:A|B`) is an openCypher extension not yet enabled in the primary GQL grammar.
  - **Contract Status**: Explicitly categorized under `UNSUPPORTED_LANGUAGE_FEATURE` in the query contract.

### 2.4 Re-used Relationship Variables in Mutations (`Create6#10-#14`, `Merge8#1`)
- **Component**: Physical Executor (`_execute_create_clause`, `_execute_merge_clause`)
- **Minimal Reproducible Case**:
  - **Query**:
    ```cypher
    UNWIND [1, 2] AS x
    CREATE (a)-[r:LINK]->(b)
    RETURN count(r)
    ```
  - **Expected**: 2 distinct link edges created.
  - **Actual**: `ValueError: Edge 'r' already exists with different label/endpoints`
  - **Root Cause**: Edge generation assigns the edge variable name `'r'` as the primary edge ID if explicit ID generation is omitted during iterative unwinding.
  - **Remediation Target**: When creating edges iteratively from row streams, generate synthetic unique identifiers `f"{var}_{uuid4().hex[:8]}"` when an edge with that key already exists.

### 2.5 Path Return Functions (`relationships(p)`)
- **Component**: Physical Evaluator (`_eval_function`)
- **Minimal Reproducible Case**:
  - **Query**:
    ```cypher
    MATCH p = (a)-[r]->(b) RETURN relationships(p) AS rels
    ```
  - **Expected**: List of edge representations `[ <Edge r> ]`.
  - **Actual**: `FAIL_WRONG_RESULT` (format mismatch in tabular comparison)
  - **Root Cause**: Path edge sequences are tracked as internal tuple of IDs `__path_edges__`, and returning them as a list of `Edge` entities requires entity unwrapping in tabular serializers.

---

## 3. Negative Syntax Test Lenience (42 Scenarios)

42 scenarios classified under `FAIL_WRONG_RESULT` represent negative syntax tests where openCypher expects compilation to fail with `syntax_error`, but GQL-Core's parser was overly permissive:
- Deleting raw integer literals: `DELETE 1` (expected `syntax_error`, executed with no-op).
- Deleting naked labels: `DELETE :Label` (expected `syntax_error`).
- Setting invalid property syntax: `SET n.prop = = 1`.
- Missing YIELD on in-query procedure calls without outputs.

These do not represent incorrect query results for valid user queries, but rather opportunities to tighten grammar productions to fail early and explicitly on invalid input.

---

## 4. Defect Tracking & Mitigation Plan

| Defect ID | Category | Subsystem | Planned Mitigation | Release Impact |
|---|---|---|---|---|
| `DEF-TCK-01` | Multi-Label Matching | Parser & Executor | Add `labels: tuple[str, ...]` to `NodePat` and intersect node IDs | Planned for `0.2.0` |
| `DEF-TCK-02` | Disconnected MATCH | Query Planner | Implement CrossProductOp for disjoint patterns | Planned for `0.2.0` |
| `DEF-TCK-03` | Edge ID Collisions | Mutation Engine | Generate UUIDs for anonymous and looped created edges | Planned for `0.2.0` |
| `DEF-TCK-04` | Strict Syntax Rejections | Parser Grammar | Add negative validation passes in `SemanticValidator` | Non-blocking for Alpha |
| `DEF-TCK-05` | Map Projections | Grammar & IR | Add `MapProjection` AST node `n { .prop }` | Planned for `0.3.0` |
