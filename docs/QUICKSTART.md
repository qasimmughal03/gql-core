# GQL-Core Quickstart Guide

This guide walks you through the core capabilities of GQL-Core (`0.2.0a1`) in under five minutes.

---

## 1. Installation

GQL-Core requires Python 3.11 or later. Clone and install in editable mode:

```bash
git clone https://github.com/qasimmughal03/gql-core.git
cd gql-core
python -m pip install -e .
```

To include development and benchmark utilities:

```bash
python -m pip install -e ".[dev,benchmark]"
```

Verify your installation:

```bash
gql-core --version
```

---

## 2. Textual Cypher / GQL Queries

Construct an in-memory `PropertyGraph` and query it using openCypher pattern syntax:

```python
import gql_core
from gql_core import PropertyGraph, Node, Edge

# 1. Initialize an empty graph
graph = PropertyGraph()

# 2. Add nodes with labels and properties
graph.add_node(Node(id="alice", label="Person", props={"name": "Alice", "dept": "Eng"}))
graph.add_node(Node(id="bob", label="Person", props={"name": "Bob", "dept": "Eng"}))
graph.add_node(Node(id="charlie", label="Person", props={"name": "Charlie", "dept": "Product"}))

# 3. Add directed relationships
graph.add_edge(Edge(id="e1", label="KNOWS", src="alice", dst="bob", props={"since": 2022}))
graph.add_edge(Edge(id="e2", label="KNOWS", src="bob", dst="charlie", props={"since": 2023}))

# 4. Execute a Cypher query
results = gql_core.run(
    """
    MATCH (a:Person)-[:KNOWS]->(b:Person)
    WHERE a.name = 'Alice'
    RETURN b.name AS friend, b.dept AS department
    """,
    graph,
)

print(results)
# Output: [{'friend': 'Bob', 'department': 'Eng'}]
```

For variable-length path traversal (multi-hop):

```python
# Traverse 1 to 2 hops from Alice
multi_hop = gql_core.run(
    """
    MATCH (a:Person {name: 'Alice'})-[:KNOWS*1..2]->(f:Person)
    RETURN f.name AS reachable_friend
    ORDER BY reachable_friend ASC
    """,
    graph,
)
print(multi_hop)
# Output: [{'reachable_friend': 'Bob'}, {'reachable_friend': 'Charlie'}]
```

A runnable script is available in [`examples/example_a_graph_query.py`](../examples/example_a_graph_query.py).

---

## 3. Zero-Friction Graph Ingestion

GQL-Core provides direct constructors from Python records, edge lists, dictionaries, and NetworkX graphs:

```python
from gql_core import PropertyGraph

# A. From records (nodes and edges)
records_nodes = [
    {"id": "svc_auth", "label": "Service", "tier": "critical"},
    {"id": "svc_pay", "label": "Service", "tier": "critical"},
]
records_edges = [
    {"src": "svc_auth", "dst": "svc_pay", "label": "CALLS", "timeout_ms": 500}
]
g1 = PropertyGraph.from_records(records_nodes, records_edges)

# B. From edge tuples: (src, dst, label, properties)
edges = [
    ("Alice", "Bob", "MANAGES", {"since": 2021}),
    ("Bob", "Charlie", "MANAGES", {"since": 2023}),
]
g2 = PropertyGraph.from_edges(edges)

# C. From a dictionary containing 'nodes' and 'edges' arrays
data = {
    "nodes": [{"id": "n1", "label": "Item"}, {"id": "n2", "label": "Item"}],
    "edges": [{"id": "e1", "src": "n1", "dst": "n2", "label": "RELATED"}],
}
g3 = PropertyGraph.from_dict(data)

# D. From NetworkX (requires networkx)
import networkx as nx

nx_graph = nx.DiGraph()
nx_graph.add_node(1, type="Host", ip="10.0.0.1")
nx_graph.add_node(2, type="Host", ip="10.0.0.2")
nx_graph.add_edge(1, 2, label="ROUTES_TO", latency=4)
g4 = PropertyGraph.from_networkx(nx_graph)
```

---

## 4. Programmatic Typed Query Plans (`PlanBuilder`)

For applications, autonomous LLM agents, and compiler backends, GQL-Core exposes a type-safe relational/graph intermediate representation (IR):

```python
from gql_core import (
    PlanBuilder, PropertyGraph, Node, Edge,
    col, eq, gt, lit, prop, validate_logical_plan, execute_plan
)

# 1. Construct plan using the fluent builder
plan = (
    PlanBuilder.scan("s", "Service")
    .filter(eq(prop("s", "tier"), lit("critical")))
    .expand("CALLS", to_var="target", from_var="s")
    .filter(gt(prop("target", "latency"), lit(50)))
    .project(
        (prop("s", "id"), "source_service"),
        (prop("target", "id"), "target_service"),
    )
    .sort((col("source_service"), "ASC"))
    .limit(10)
    .build()
)

# 2. Validate plan statically
report = validate_logical_plan(plan, strict=True)
assert report.is_valid

# 3. Execute deterministically
# result = execute_plan(plan, graph)
```

A runnable script is available in [`examples/example_b_typed_plan.py`](../examples/example_b_typed_plan.py).

---

## 5. Declarative Ontology & Datalog Inference

Derive relationships and facts automatically using rule-based reasoning:

```python
from gql_core import PropertyGraph, Node, Edge, run
from gql_core.inference import (
    InferenceEngine, make_transitive_rule, make_inverse_rule, make_composition_rule
)

graph = PropertyGraph()
graph.add_node(Node("team_a", "Team"))
graph.add_node(Node("eng_dept", "Department"))
graph.add_node(Node("corp", "Company"))

graph.add_edge(Edge("e1", "PART_OF", "team_a", "eng_dept"))
graph.add_edge(Edge("e2", "PART_OF", "eng_dept", "corp"))

# Configure rules
engine = InferenceEngine()
engine.add_rule(make_transitive_rule("PART_OF"))

# Execute fixed-point inference
facts_by_rel, derived_facts = engine.infer(graph)

for fact in derived_facts:
    print(f"Inferred: {fact.args[0]} -[:{fact.args[1]}]-> {fact.args[2]} [Rule: {fact.rule_name}]")
# Inferred: team_a -[:PART_OF]-> corp [Rule: transitive_PART_OF]

# Materialize inferred relationships back into the graph
engine.materialize(graph)

# Query materialized edges using Cypher
print(run("MATCH (t:Team)-[:PART_OF]->(c:Company) RETURN t, c", graph))
```

A runnable script is available in [`examples/example_c_ontology_inference.py`](../examples/example_c_ontology_inference.py).

---

## 6. Command-Line Interface (CLI)

GQL-Core installs the `gql-core` console executable:

```bash
# Execute a Cypher query over a JSON graph file
gql-core query --data examples/sample_graph.json \
  "MATCH (p:Person) RETURN p.name AS name ORDER BY name ASC"

# Output as an aligned ASCII table
gql-core query --data examples/sample_graph.json --table \
  "MATCH (p:Person) RETURN p.name AS name"

# Check version
gql-core version
```

---

## 7. Next Steps

- Consult the [API Reference](API_REFERENCE.md) for complete function signatures.
- Read the [Supported Query Contract](SUPPORTED_QUERY_CONTRACT.md) for supported openCypher syntax.
- Explore the [Packaging Guide](PACKAGING.md) for build, testing, and distribution details.
