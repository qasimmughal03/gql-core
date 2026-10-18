# GQL-Core Deterministic Ontology Inference Engine

**Version**: 1.0  
**Package**: `gql_core.inference`  
**Reference Models**: [`InferenceEngine`](file:///c:/Users/HP/Documents/Portfolio/knowledge-graoh-with-formal-query/gql_core/inference/engine.py), [`InferenceRule`](file:///c:/Users/HP/Documents/Portfolio/knowledge-graoh-with-formal-query/gql_core/inference/rules.py), [`Fact`](file:///c:/Users/HP/Documents/Portfolio/knowledge-graoh-with-formal-query/gql_core/inference/rules.py)  

---

## 1. Overview

GQL-Core incorporates an in-memory, deterministic Datalog-like rule inference engine. The engine compiles declarative ontology rules into a stratified fixed-point evaluator that automatically derives:
- Subtype facts (`(x:Dog) => (x:Animal)`)
- Inverse relationships (`(x)-[PARENT_OF]->(y) => (y)-[CHILD_OF]->(x)`)
- Symmetric relationships (`(x)-[FRIEND]->(y) => (y)-[FRIEND]->(x)`)
- Transitive closures (`(x)-[PART_OF]->(y) AND (y)-[PART_OF]->(z) => (x)-[PART_OF]->(z)`)
- User-defined implication rules (e.g. indirect management hierarchies).

---

## 2. Rule Representation

Rules use a safe Datalog syntax:
```text
Head :- Body_1, Body_2, ...
```

### 2.1 Core Components
- **`Fact(predicate, args, is_inferred, rule_name, evidence)`**: A ground truth (e.g. `Fact("rel", ("paris", "LOCATED_IN", "france"))`).
- **`Atom(predicate, args, is_negated)`**: A pattern atom with variables (e.g. `?x`, `?y`) and constants.
- **`InferenceRule(name, head, body, description)`**: A declarative derivation rule.

### 2.2 Safety Guarantees
- Every variable appearing in the `head` must appear in at least one positive (non-negated) `body` atom.
- Arbitrary executable Python functions or code injection are strictly prohibited.
- Negation is evaluated under stratified assumptions.

---

## 3. High-Performance Indexing & Fixed-Point Algorithm

The inference engine uses semi-naive fixed-point iteration with argument-position candidate indexing:

```mermaid
flowchart TD
    A[Extract Ground Asserted Facts from PropertyGraph] --> B[Build Argument Index: (predicate, pos, val) -> Facts]
    B --> C[Iteration Loop: Evaluate Rules against Fact Index]
    C --> D{New Facts Derived?}
    D -- Yes --> E[Deduplicate against Seen Tuples & Update Index]
    E --> F{Bound Reached (max_iterations or max_facts)?}
    F -- No --> C
    F -- Yes --> G[Return All Facts & Derived List]
    D -- No --> G
```

### 3.1 Performance Characteristics
- By indexing facts by `(predicate, arg_position, arg_value)`, unifications avoid nested $O(|F|^2)$ loops.
- In benchmarks, deriving 1,176 transitive closure facts over a 50-step linear chain executes in **under 20 ms**.
- Guaranteed termination: bounded by `max_iterations` (default 50) and `max_facts` (default 250,000), preventing infinite loops in cyclic graphs.

---

## 4. Provenance & Non-Double-Counting

Every inferred fact preserves full provenance:
- **`is_inferred: True`**
- **`rule_name`**: Name of the rule that generated the derivation.
- **`evidence`**: Tuple of parent ground facts that satisfied the rule premises.

Asserted facts and inferred facts are strictly distinguished. If a relationship is already asserted in the graph, the inference engine skips redundant edge creation, preventing double-counting in path traversals and aggregations.

---

## 5. Execution Modes

### 5.1 Virtual Query Overlay
[`engine.create_overlay_graph(graph)`](file:///c:/Users/HP/Documents/Portfolio/knowledge-graoh-with-formal-query/gql_core/inference/engine.py) returns a lightweight copy containing asserted plus derived facts, allowing queries to seamlessly traverse derived edges without altering the source dataset.

### 5.2 Controlled Materialization
[`engine.materialize(graph)`](file:///c:/Users/HP/Documents/Portfolio/knowledge-graoh-with-formal-query/gql_core/inference/engine.py) directly inserts derived edges into the `PropertyGraph`, tagging each edge with:
```python
props={"is_inferred": True, "inferred_by": "transitive_LOCATED_IN"}
```
and annotating node properties with `inferred_types`.
