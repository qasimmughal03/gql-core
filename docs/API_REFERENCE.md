# GQL-Core API Reference

This document provides a concise reference for the public Python API surface of `gql_core` (`0.2.0a1`).

---

## 1. Top-Level Query Execution

Imported directly from `gql_core`:

```python
import gql_core
from gql_core import run, parse, plan
```

### `run(query: str, graph: PropertyGraph, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]`
Parses, statically type-checks, optimizes, and executes an openCypher / ISO GQL textual query against a `PropertyGraph`.
- **`query`**: Textual query string (e.g., `MATCH (n:Person) RETURN n.name`).
- **`graph`**: Target in-memory `PropertyGraph` instance.
- **`parameters`**: Optional dictionary of runtime query parameters `$param`.
- **Returns**: A list of row dictionaries mapping projected column aliases to values.
- **Raises**:
  - `SyntaxError`: Static type errors, parse errors, or unknown procedures.
  - `SemanticError`: Scope errors, duplicate aliases, or invalid merge patterns.
  - `EntityNotFoundError`: Accessing deleted nodes or edges.
  - `ConstraintVerificationError`: Deleting nodes with active relationships without `DETACH`.

### `parse(query: str) -> Query`
Parses a query string into an Abstract Syntax Tree (AST) without executing it.

### `plan(query: str) -> RelOp`
Compiles an openCypher query string into a logical operator tree (`RelOp`).

---

## 2. In-Memory Graph Data Structures

```python
from gql_core import PropertyGraph, Node, Edge, Path
```

### `Node(id: Any, label: str = "Node", props: dict[str, Any] | None = None, labels: tuple[str, ...] = ())`
Represents an individual graph node.
- **`id`**: Unique node identifier (primitives supported: `str`, `int`, etc.).
- **`label`**: Primary node label.
- **`props`**: Dictionary of node property key-value pairs.
- **`labels`**: Tuple of all labels attached to the node (including secondary labels).

### `Edge(id: Any, label: str, src: Any, dst: Any, props: dict[str, Any] | None = None)`
Represents a directed relationship between two nodes.
- **`id`**: Unique relationship identifier.
- **`label`**: Relationship type name (e.g., `"KNOWS"`).
- **`src`**: Node identifier of the source endpoint.
- **`dst`**: Node identifier of the destination endpoint.
- **`props`**: Dictionary of edge property key-value pairs.

### `Path(nodes: tuple[Node, ...], relationships: tuple[Edge, ...])`
Represents a traversed graph path composed of alternating nodes and edges.
- `len(path)` returns the number of relationships in the path.

### `PropertyGraph`
The in-memory graph container.
- `add_node(node: Node) -> None`
- `add_edge(edge: Edge) -> None`
- `get_node(node_id: Any) -> Node | None`
- `get_edge(edge_id: Any) -> Edge | None`
- `delete_node(node_id: Any, detach: bool = False) -> None`
- `delete_edge(edge_id: Any) -> None`
- `neighbors_out(node_id: Any, label: str | None = None) -> list[tuple[Node, Edge]]`
- `neighbors_in(node_id: Any, label: str | None = None) -> list[tuple[Node, Edge]]`
- `nodes_by_label(label: str) -> list[Node]`

#### Ingestion Classmethods:
- `PropertyGraph.from_records(nodes: list[dict], edges: list[dict]) -> PropertyGraph`: Constructs graph from record dictionaries. Preserves falsy property values and integer IDs.
- `PropertyGraph.from_edges(edges: list[tuple]) -> PropertyGraph`: Constructs graph from tuples `(src, dst, [label], [props])`.
- `PropertyGraph.from_dict(data: dict[str, list]) -> PropertyGraph`: Expects `{"nodes": [...], "edges": [...]}`.
- `PropertyGraph.from_networkx(G: Any, ...) -> PropertyGraph`: Converts NetworkX `Graph`, `DiGraph`, `MultiGraph`, or `MultiDiGraph`.

---

## 3. Programmatic Typed Query Plan API

```python
from gql_core import PlanBuilder, validate_logical_plan, execute_plan
from gql_core import col, lit, prop, eq, ne, lt, lte, gt, gte, and_, or_, not_, is_null
```

### `PlanBuilder`
Fluent builder for constructing immutable logical operator trees (`RelOp`).

- `PlanBuilder.scan(var: str, label: str | None = None, **property_filters) -> PlanBuilder`
- `.filter(predicate: BoolExpr) -> PlanBuilder`
- `.expand(rel_type: str, to_var: str, from_var: str, direction: str = "out") -> PlanBuilder`
- `.project(*projections: tuple[ValueExpr, str], distinct: bool = False) -> PlanBuilder`
- `.sort(*order_terms: tuple[ColRef, str]) -> PlanBuilder`
- `.skip(count: int) -> PlanBuilder`
- `.limit(count: int) -> PlanBuilder`
- `.join(other_plan: RelOp, on: tuple[str, str], how: str = "inner") -> PlanBuilder`
- `.union(other_plan: RelOp, distinct: bool = True) -> PlanBuilder`
- `.build() -> RelOp`: Validates and returns the immutable logical operator tree.

### Plan Validation & Execution:
- `validate_logical_plan(root: RelOp, strict: bool = True) -> ValidationReport`: Validates variable scoping, operator compatibility, and schema constraints.
- `execute_plan(plan: RelOp, graph: PropertyGraph) -> dict[str, Any]`: Executes the plan and returns `{"rows": list[dict], "columns": list[str]}`.

### Expression Builders:
- `prop(var: str, property_name: str) -> Property`: Reference an entity property.
- `col(column_name: str) -> ColRef`: Reference a tabular column in sort/project.
- `lit(value: Any) -> Literal`: Constant literal value.
- Comparisons: `eq(a, b)`, `ne(a, b)`, `lt(a, b)`, `lte(a, b)`, `gt(a, b)`, `gte(a, b)`.
- Boolean logic: `and_(*exprs)`, `or_(*exprs)`, `not_(expr)`.

---

## 4. Ontology & Datalog Inference Engine

```python
from gql_core.inference import (
    InferenceEngine,
    InferenceRule,
    Fact,
    make_subtype_rule,
    make_inverse_rule,
    make_symmetric_rule,
    make_transitive_rule,
    make_composition_rule,
)
```

### `InferenceEngine(schema: OntologySchema | None = None, max_iterations: int = 50, max_facts: int = 250000)`
Stratified semi-naive forward chaining inference engine.
- `add_rule(rule: InferenceRule) -> None`: Registers an inference rule.
- `infer(graph: PropertyGraph) -> tuple[dict[str, set[Fact]], list[Fact]]`: Computes the deductive fixed point and returns `(facts_by_relation, all_derived_facts)`.
- `materialize(graph: PropertyGraph) -> int`: Directly inserts derived relationship edges into the graph and returns count of added edges.
- `create_overlay_graph(graph: PropertyGraph) -> PropertyGraph`: Returns an overlay copy with inferred edges added without mutating the source graph.

### Rule Factories:
- `make_transitive_rule(rel_name: str) -> InferenceRule`: Transitive closure ($A \to B \land B \to C \implies A \to C$).
- `make_inverse_rule(rel_name: str, inverse_name: str) -> InferenceRule`: Inverse relationship ($A \to B \implies B \to A$).
- `make_symmetric_rule(rel_name: str) -> InferenceRule`: Symmetric relationship ($A \to B \iff B \to A$).
- `make_composition_rule(derived: str, rel1: str, rel2: str) -> InferenceRule`: Relational composition ($A \xrightarrow{rel1} B \land B \xrightarrow{rel2} C \implies A \xrightarrow{derived} C$).
- `make_subtype_rule(sub_type: str, super_type: str) -> InferenceRule`: Subtype hierarchy propagation.

---

## 5. Temporal Types (`gql_core.query.cypher_temporal`)

```python
from gql_core.query.cypher_temporal import (
    Date, Time, LocalTime, DateTime, LocalDateTime, Duration
)
```

All types conform to openCypher and ISO-8601 string specifications with support for:
- Component extraction (`.year`, `.month`, `.day`, `.hour`, `.minute`, `.second`, `.timezone`, etc.).
- Arithmetic with `Duration` instances (`+`, `-`).
- Functions: `duration.between`, `duration.inMonths`, `duration.inDays`, `duration.inSeconds`, `date.truncate`, `datetime.truncate`.
