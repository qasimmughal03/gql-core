# GQL-Core

**Embedded graph querying and typed logical reasoning for Python.**

GQL-Core is an experimental in-memory property-graph engine. Work with labeled nodes and relationships, execute a Cypher-inspired query language, build validated queries through a typed Python API, and derive relationships using declarative inference rules—without a separate database server.

**Version:** `0.2.0a2` · **Stage:** public alpha candidate · **License:** Apache-2.0 · **Python:** 3.11+

> **Alpha software.** GQL-Core is not a production database, a complete ISO/IEC 39075:2024 implementation, or a certified openCypher implementation. External compatibility scores describe a specific pinned test corpus, not universal query correctness.

## Highlights

- **Graph storage:** in-memory nodes, directed relationships, multi-label nodes, properties, adjacency and label indexes.
- **Declarative queries:** matching, filtering, path traversal, grouping, sorting, `WITH`, `UNWIND`, selected updates, and built-in expressions.
- **Typed query plans:** compose `Scan`, `Expand`, `Filter`, `Project`, joins, set operators, quantified predicates, and aggregation through `PlanBuilder`.
- **Ontology reasoning:** explicit subtype, inverse, symmetric, transitive, and relationship-composition inference rules, with provenance.
- **Optional natural-language interface:** translate questions to query text using a configured LLM backend; formal execution itself does not require an LLM.
- **Measured accuracy:** checked against published benchmarks (openCypher TCK, CypherBench, MetaQA, LDBC SNB) using their own data, gold answers and metrics; see [Accuracy and benchmarks](#accuracy-and-benchmarks).

## Install

```bash
python -m pip install gql-core
gql-core --version
```

The package is on PyPI as [`gql-core`](https://pypi.org/project/gql-core/) (alpha, `0.2.0a2`). To work from source:

```bash
git clone https://github.com/qasimmughal03/knowledge-graoh-with-formal-query.git
cd knowledge-graoh-with-formal-query
git checkout feat/implementation
python -m pip install -e .
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

A runnable version is in [`examples/quickstart.py`](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/examples/quickstart.py).

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

A standalone typed plan script is in [`examples/example_b_typed_plan.py`](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/examples/example_b_typed_plan.py).

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

A standalone inference script is in [`examples/example_c_ontology_inference.py`](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/examples/example_c_ontology_inference.py).

See the [typed query API](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/TYPED_QUERY_API.md), [operator reference](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/LOGICAL_OPERATOR_SPEC.md), and [ontology/inference guide](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/INFERENCE_ENGINE.md).

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

Use `PropertyGraph.from_records(nodes, edges)`, `PropertyGraph.from_edges(...)`, or `PropertyGraph.from_networkx(G)` (requires `networkx`). For the CLI's graph JSON format, see [`examples/sample_graph.json`](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/examples/sample_graph.json).

`from_dict` expects an object containing `nodes` and `edges` arrays; it is **not** an adjacency-dictionary adapter.

## Supported functionality and boundaries

GQL-Core implements a substantial, evolving subset of Cypher-like patterns and expressions, including multi-clause pipelines and mutations. Its typed plan API additionally exposes relational algebra and graph reasoning primitives. **The two APIs do not have identical coverage.**

Not all openCypher syntax is supported. In particular, the release documents exclude certain nested correlated `EXISTS` text expressions and relationship-type disjunctions. Consult [the supported query contract](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/SUPPORTED_QUERY_CONTRACT.md) for exact syntax and behavior.

Execution semantics include relationship trail uniqueness, three-valued Boolean logic, null propagation, and bag/multiset behavior where applicable. The graph is held in memory; it does not provide database durability, transactional isolation, or distributed execution. Concurrent mutations require application-level synchronization.

## Accuracy and benchmarks

Every number below comes from a **published benchmark** run with its own data, gold answers and
official metric, or, where marked, from our own check against independently computed ground
truth. Nothing here is scored against hand-written expected values. Each row gives the sample
size it comes from.

### Query engine: does GQL-Core return the right answer?

| Benchmark | What is checked | Result |
| --- | --- | ---: |
| [openCypher TCK](https://github.com/opencypher/openCypher) `2024.3` | Language conformance scenarios: results, errors and side effects | **3,879 / 3,879** supported scenarios pass (18 explicitly excluded of 3,897) |
| [CypherBench](https://huggingface.co/datasets/megagonlabs/cypherbench) test split ([paper](https://arxiv.org/abs/2412.18702)), measured at commit `43cab07` | All 2,348 gold Cypher queries run on GQL-Core over 7 real Wikidata-derived graphs (up to 885k nodes and 1.9M relationships), compared with the answers **Neo4j** produced, using the official execution-accuracy metric | **98.21%** (2,306 / 2,348); **100%** when rows that differ only in the order of tied `ORDER BY` keys are counted as matches |
| [LDBC SNB](https://ldbcouncil.org/benchmarks/snb/) SF0.1 (unaudited) | Official query parameter cases on a 327,588-node, 1,477,965-relationship graph | **4 / 4** across 2 official query types |
| Hetionet v1.0 (our own evaluation, not a published benchmark) | 5 Cypher queries and one Datalog metapath rule on real biomedical data, each compared with an independent plain-Python computation | **6 / 6** agree; 27,498 derived facts equal to the independent join |
| Project test suite | Unit and regression tests | **355 / 355** |

On CypherBench there were no errors and no timeouts (120 s limit, as in the official
evaluation). All 42 official failures are `ORDER BY` queries whose tied rows come back in a
different order from Neo4j's. openCypher leaves that order undefined, but the official metric
counts it as a failure, so we report both numbers.

| CypherBench graph | nba | flight_accident | fictional_character | company | geography | movie | politics |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Questions | 270 | 189 | 385 | 347 | 366 | 401 | 390 |
| Execution accuracy | 98.15% | 98.94% | 100% | 96.54% | 98.36% | 98.50% | 97.18% |

### Natural language → Cypher: how accurate is `ask()`?

`ask()` asks an LLM to write the query, then runs it on GQL-Core. **Its accuracy depends mainly on
the model you connect, not on the engine.** The engine runs the generated queries correctly, as
measured above. These numbers use a deliberately small local model, `qwen2.5-coder:3b` (3.1B
parameters, Q4_K_M) through Ollama on a CPU-only laptop, with the benchmarks' zero-shot protocol
(temperature 0, no examples, no retries). They are a baseline, not a ceiling.

| Benchmark | Sample (seeded) | Result |
| --- | --- | --- |
| CypherBench NL→Cypher (official zero-shot prompt) | 210 of 2,348 (30 per graph) | 13.3% execution accuracy; 92.4% of generated queries run. By graph: flight_accident 26.7%, nba 20.0%, fictional_character and movie 13.3%, politics 10.0%, company 6.7%, geography 3.3% |
| MetaQA 1-hop | 100 of 9,947 | 67% exact match, 70% F1, 72% at least one correct answer |
| MetaQA 2-hop | 100 of 14,872 | 0% exact match |
| MetaQA 3-hop | 100 of 14,274 | 0% exact match, 2% at least one correct answer |

A 3B model handles direct lookups and one-hop questions. It does not reliably compose multi-hop
paths: it stops after one hop, reverses relationship directions, or invents relationships that
are not in the schema. 92% (CypherBench) to 99% (MetaQA) of the generated queries run. Every query that fails is
invalid Cypher that Neo4j would also reject, and the engine reproduces every CypherBench gold
answer, so the misses are wrong queries rather than engine failures. On CypherBench the model scores 0% on unions, `OPTIONAL MATCH`, comparisons and
time-sensitive questions. Expect much better results from larger models; the
[CypherBench paper](https://arxiv.org/abs/2412.18702) reports results for a range of models.
Measure your own with the commands below.

### What these results do not show

They are version- and harness-scoped results, not ISO/IEC 39075 certification, complete Cypher
conformance, or evidence of production reliability. The LDBC study is unaudited and covers a
limited read-query subset; latency depends on the machine, dataset and commit (see
[LDBC coverage](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/LDBC_QUERY_COVERAGE.md)). The programs in `examples/domains/` (legal,
software supply chain, biomedical) are illustrative demonstrations on small hand-built graphs.
They show how to use the API and are not accuracy evidence.

### Reproduce

Benchmark datasets are downloaded on demand and are not bundled in the wheel.

```bash
python -m pip install -e ".[dev,benchmark]"
python -m benchmark.tck.runner                                    # openCypher TCK
python -m benchmark.cypherbench.download
PYTHONHASHSEED=0 python -m benchmark.cypherbench.run_engine_parity # engine vs Neo4j gold answers
python -m benchmark.cypherbench.run_nl2cypher --model qwen2.5-coder:3b --per-graph 30 --seed 0
python -m benchmark.metaqa.run_nl2cypher --model qwen2.5-coder:3b --per-hop 100 --seed 0
```

Methodology, per-category breakdowns and the engine bugs these benchmarks found are in
[docs/NL_BENCHMARKS.md](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/NL_BENCHMARKS.md) and the
[release correctness report](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/RELEASE_CORRECTNESS_REPORT.md). Per-question results are in
`benchmark/results/`.

## Build and release verification

```bash
python -m pip install -e ".[dev,benchmark]"
python -m pytest tests/
python -m build
python -m twine check dist/*
```

The test suite uses upstream TCK fixtures; see [`docs/PACKAGING.md`](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/PACKAGING.md) for the required preparation and wheel smoke test. CI verifies the distribution in an isolated Python environment. Uploading to TestPyPI or PyPI is a **separate manual step**, not part of CI.

## Documentation

- [Unified architecture and verification report](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/UNIFIED_DOCUMENTATION.md)
- [Quickstart walkthrough](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/QUICKSTART.md)
- [Python API reference](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/API_REFERENCE.md)
- [Supported textual query contract](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/SUPPORTED_QUERY_CONTRACT.md)
- [Typed Python query API](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/TYPED_QUERY_API.md)
- [Ontology and inference](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/INFERENCE_ENGINE.md)
- [Logical operator specification](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/LOGICAL_OPERATOR_SPEC.md)
- [Release correctness report](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/RELEASE_CORRECTNESS_REPORT.md)
- [CypherBench and MetaQA results and methodology](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/NL_BENCHMARKS.md)
- [TCK scenario failures and methodology](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/TCK_FAILURE_ANALYSIS.md)
- [Packaging and release checklist](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/PACKAGING.md)
- [Release notes (v0.2.0a2)](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/RELEASE_NOTES_0.2.0a2.md) · [v0.2.0a1](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/docs/RELEASE_NOTES_0.2.0a1.md)

## Contributing

Open an issue with a minimal graph, the exact query/plan, expected output, actual output, Python version, and relevant stack trace. New operators and bug fixes should come with regression tests and, where applicable, a compatibility scenario.

## License

[Apache License 2.0](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/blob/feat/implementation/LICENSE). GQL-Core is an independent project. Referencing ISO, openCypher, Neo4j, or LDBC does not imply affiliation or official certification.
