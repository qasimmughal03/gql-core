# GQL-Core

**Embedded graph querying and typed logical reasoning for Python.**

GQL-Core is an experimental in-memory property-graph engine. Work with labeled nodes and relationships, execute a Cypher-inspired query language, build validated queries through a typed Python API, and derive relationships using declarative inference rules—without a separate database server.

**Version:** `0.2.0a1` · **Stage:** public alpha candidate · **License:** Apache-2.0 · **Python:** 3.11+

> **Alpha software.** GQL-Core is not a production database, a complete ISO/IEC 39075:2024 implementation, or a certified openCypher implementation. External compatibility scores describe a specific pinned test corpus, not universal query correctness.

## Highlights

- **Graph storage:** in-memory nodes, directed relationships, multi-label nodes, properties, adjacency and label indexes.
- **Declarative queries:** matching, filtering, path traversal, grouping, sorting, `WITH`, `UNWIND`, selected updates, and built-in expressions.
- **Typed query plans:** compose `Scan`, `Expand`, `Filter`, `Project`, joins, set operators, quantified predicates, and aggregation through `PlanBuilder`.
- **Ontology reasoning:** explicit subtype, inverse, symmetric, transitive, and relationship-composition inference rules, with provenance.
- **Optional natural-language interface:** translate questions to query text using a configured LLM backend; formal execution itself does not require an LLM.
- **Reproducible evaluation:** openCypher TCK compatibility harness, LDBC SNB-derived workload, and pytest regression suite.

## Install

The alpha is available from this repository. **Do not assume that `gql-core` is already published on PyPI.**

```bash
git clone https://github.com/qasimmughal03/knowledge-graoh-with-formal-query.git
cd knowledge-graoh-with-formal-query
git checkout feat/implementation
python -m pip install -e .
gql-core --version
```

For contributors:

```bash
python -m pip install -e ".[dev,benchmark]"
```

The runtime uses Lark, PyYAML, and Requests. NetworkX integration is optional. The `ask()` interface needs a compatible, available LLM service or client; it is not an offline heuristic answering system.

## Quickstart: Python API

```python
from gql_core import Edge, Node, PropertyGraph, run

graph = PropertyGraph()
graph.add_node(Node(id="alice", label="Person", props={"name": "Alice"}))
graph.add_node(Node(id="bob", label="Person", props={"name": "Bob"}))
graph.add_edge(Edge(id="e1", label="KNOWS", src="alice", dst="bob"))

rows = run(
    "MATCH (a:Person)-[:KNOWS]->(b:Person) "
    "WHERE a.name = 'Alice' RETURN b.name AS friend",
    graph,
)
print(rows)  # [{'friend': 'Bob'}]
```

A runnable version is in [`examples/quickstart.py`](examples/quickstart.py).

### Typed query plans

For LLM agents and Python applications, structured plans can be validated independently of text-query generation.

```python
from gql_core import PlanBuilder, eq, execute_plan, lit, prop

plan = (
    PlanBuilder.scan("p", "Person")
    .filter(eq(prop("p", "name"), lit("Alice")))
    .project((prop("p", "name"), "name"))
    .build()
)
result = execute_plan(plan, graph)
print(result["rows"])  # [{'name': 'Alice'}]
```

A standalone typed plan script is in [`examples/example_b_typed_plan.py`](examples/example_b_typed_plan.py).

### Ontology inference

Derive new graph relationships declaratively using Datalog-style rules without modifying source facts:

```python
from gql_core.inference import InferenceEngine, make_transitive_rule

# Derive transitive relationships: if A PART_OF B and B PART_OF C => A PART_OF C
engine = InferenceEngine()
engine.add_rule(make_transitive_rule("PART_OF"))

facts_by_rel, derived_facts = engine.infer(graph)
engine.materialize(graph)  # Materializes inferred edges back into the graph
```

A standalone inference script is in [`examples/example_c_ontology_inference.py`](examples/example_c_ontology_inference.py).

See the [typed query API](docs/TYPED_QUERY_API.md), [operator reference](docs/LOGICAL_OPERATOR_SPEC.md), and [ontology/inference guide](docs/INFERENCE_ENGINE.md).

## Quickstart: CLI

A small example dataset is included so this command runs after installing the package from a repository checkout:

```bash
gql-core query --data examples/sample_graph.json \
  "MATCH (p:Person) RETURN p.name AS name ORDER BY name ASC"
```

Available commands: `query`, `ask`, `validate`, `ingest`, `mirror`, `benchmark`, and `version`. Use `gql-core --help` for the authoritative argument list. The CLI command is **`query`**, not `run`.

For the natural-language command, set up an Ollama-compatible backend or supply a client through the Python API. `gql-core ask` does not automatically provide a hosted model.

## Project structure

| Directory/module | Purpose |
| --- | --- |
| `gql_core/graph.py` | `PropertyGraph`, `Node`, `Edge`, `Path`, graph adapters |
| `gql_core/query/` | Grammar, parser, semantic validation, query execution |
| `gql_core/ir.py`, `builder.py` | Typed expressions, logical operators, fluent plan building |
| `gql_core/physical/` | Expression evaluation and physical execution |
| `gql_core/ontology/`, `inference/` | Typed ontology schemas and rule-based inference |
| `gql_core/ai.py` | Optional question-to-query translation |
| `benchmark/tck/` | openCypher compatibility checking |
| `benchmark/snb/` | LDBC social-network workload support |
| `examples/` | Standalone quickstart and domain examples |
| `docs/` | Technical contracts, architecture, benchmark and release reports |

### Graph adapters

Use `PropertyGraph.from_records(nodes, edges)`, `PropertyGraph.from_edges(...)`, or `PropertyGraph.from_networkx(G)` (requires `networkx`). For the CLI's graph JSON format, see [`examples/sample_graph.json`](examples/sample_graph.json).

`from_dict` expects an object containing `nodes` and `edges` arrays; it is **not** an adjacency-dictionary adapter.

## Supported functionality and boundaries

GQL-Core implements a substantial, evolving subset of Cypher-like patterns and expressions, including multi-clause pipelines and mutations. Its typed plan API additionally exposes relational algebra and graph reasoning primitives. **The two APIs do not have identical coverage.**

Not all openCypher syntax is supported. In particular, the release documents exclude certain nested correlated `EXISTS` text expressions and relationship-type disjunctions. Consult [the supported query contract](docs/SUPPORTED_QUERY_CONTRACT.md) for exact syntax and behavior.

Execution semantics include relationship trail uniqueness, three-valued Boolean logic, null propagation, and bag/multiset behavior where applicable. The graph is held in memory; it does not provide database durability, transactional isolation, or distributed execution. Concurrent mutations require application-level synchronization.

## Benchmarks and correctness

The latest repository [release correctness report](docs/RELEASE_CORRECTNESS_REPORT.md) documents results on the pinned openCypher TCK `2024.3` corpus:

| Reported evaluation | Result |
| --- | ---: |
| Expanded TCK scenarios, including Scenario Outlines | 3,897 |
| Scenarios classified as supported | 3,879 |
| Strict scenario passes in that subset | **3,879 / 3,879** |
| Explicitly excluded scenarios | 18 |
| Project unit/regression tests | **341 / 341** |
| Official LDBC SNB SF0.1 query parameter cases | **4 / 4** across **2 official query types** |

**Interpretation:** These are version- and harness-scoped results reported by the project, not ISO certification, complete Cypher conformance, or evidence of production reliability. The LDBC study is **unaudited**, covers a limited read-query subset, and reports adapted additional queries separately from official equivalent operations.

The latest reported SF0.1 graph contains 327,588 nodes and 1,477,965 relationships. Measurements depend on the exact dataset, machine, source commit, and workload; see [LDBC coverage](docs/LDBC_QUERY_COVERAGE.md) before comparing latency.

The TCK repository and large benchmark datasets are external assets, not bundled in the Python wheel. See [packaging and verification](docs/PACKAGING.md) for how to run checks. Do not compare TCK correctness percentages with LDBC query latency.

## Build and release verification

```bash
python -m pip install -e ".[dev,benchmark]"
python -m pytest tests/
python -m build
python -m twine check dist/*
```

The test suite uses upstream TCK fixtures; see [`docs/PACKAGING.md`](docs/PACKAGING.md) for the required preparation and wheel smoke test. CI verifies the distribution in an isolated Python environment. Uploading to TestPyPI or PyPI is a **separate manual step**, not part of CI.

## Documentation

- [Unified architecture and verification report](docs/UNIFIED_DOCUMENTATION.md)
- [Quickstart walkthrough](docs/QUICKSTART.md)
- [Python API reference](docs/API_REFERENCE.md)
- [Supported textual query contract](docs/SUPPORTED_QUERY_CONTRACT.md)
- [Typed Python query API](docs/TYPED_QUERY_API.md)
- [Ontology and inference](docs/INFERENCE_ENGINE.md)
- [Logical operator specification](docs/LOGICAL_OPERATOR_SPEC.md)
- [Release correctness report](docs/RELEASE_CORRECTNESS_REPORT.md)
- [TCK scenario failures and methodology](docs/TCK_FAILURE_ANALYSIS.md)
- [Packaging and release checklist](docs/PACKAGING.md)
- [Release notes (v0.2.0a1)](docs/RELEASE_NOTES_0.2.0a1.md)

## Contributing

Open an issue with a minimal graph, the exact query/plan, expected output, actual output, Python version, and relevant stack trace. New operators and bug fixes should come with regression tests and, where applicable, a compatibility scenario.

## License

[Apache License 2.0](LICENSE). GQL-Core is an independent project. Referencing ISO, openCypher, Neo4j, or LDBC does not imply affiliation or official certification.
