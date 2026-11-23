# GQL-Core

**Embedded graph querying and rule-based reasoning for Python. No database server.**

**Version:** `0.2.0a3` · **Stage:** alpha · **License:** Apache-2.0 · **Python:** 3.11+ · [PyPI](https://pypi.org/project/gql-core/)

## Why GQL-Core?

Many applications have graph-shaped data: dependencies between services, citations between
cases, interactions between drugs, people and the films they made. Querying it usually means
either running a graph database next to your application, or writing ad-hoc traversal code that
nobody else can read.

GQL-Core is a third option: a property-graph engine that runs **inside your Python process**.
You load nodes and relationships, query them with Cypher, derive new relationships with
declarative rules that record *why* each one exists, and, if you want, let a language model
write the queries from plain English, with GQL-Core checking them against the graph before they
run.

```bash
python -m pip install gql-core
```

## Features

- **Property graph in memory:** labelled nodes (several labels per node), directed
  relationships, properties, label and adjacency indexes. Load from records, JSON or NetworkX.
- **Cypher queries:** `MATCH`, `OPTIONAL MATCH`, `WHERE`, `WITH`, `UNWIND`, aggregation,
  `ORDER BY`, `UNION`, `CALL { }` and `EXISTS { }` subqueries, variable-length paths, and
  selected updates. 3,879 of 3,879 supported openCypher TCK scenarios pass.
- **Typed query plans:** build and validate a plan in Python (`PlanBuilder`) instead of
  generating text: scans, expansions, joins, set operators, quantified predicates, aggregation.
- **Rule-based reasoning:** subtype, inverse, symmetric, transitive and composition rules,
  evaluated to a fixed point. Every derived fact records the rule and the facts it came from.
- **Natural-language questions (optional):** `ask()` has a model of your choice write the query,
  then repairs reversed relationships and mis-cased values against the graph, and retries once
  with execution feedback.

## Three examples

### 1. Query a graph without running a database

```python
from gql_core import Edge, Node, PropertyGraph, run

graph = PropertyGraph()
graph.add_node(Node(id="alice", label="Person", props={"name": "Alice"}))
graph.add_node(Node(id="bob", label="Person", props={"name": "Bob"}))
graph.add_edge(Edge(id="e1", label="KNOWS", src="alice", dst="bob"))

rows = run(
    "MATCH (a:Person)-[:KNOWS]->(b:Person) WHERE a.name = 'Alice' RETURN b.name AS friend",
    graph,
)
print(rows)  # [{'friend': 'Bob'}]
```

### 2. Derive a relationship and see where it came from

```python
from gql_core import Edge, Node, PropertyGraph, run
from gql_core.inference import InferenceEngine, make_transitive_rule

g = PropertyGraph()
for id_, name in [("core", "Core Platform"), ("eng", "Engineering"), ("acme", "Acme")]:
    g.add_node(Node(id=id_, label="Unit", props={"name": name}))
g.add_edge(Edge(id="e1", label="PART_OF", src="core", dst="eng"))
g.add_edge(Edge(id="e2", label="PART_OF", src="eng", dst="acme"))

engine = InferenceEngine()
engine.add_rule(make_transitive_rule("PART_OF"))
_, derived = engine.infer(g)
for fact in derived:
    print(fact.args, "by", fact.rule_name, "from", [f.args for f in fact.evidence])
# ('core', 'PART_OF', 'acme') by transitive_PART_OF
#     from [('core', 'PART_OF', 'eng'), ('eng', 'PART_OF', 'acme')]

engine.materialize(g)  # derived edges become queryable, marked with the rule that made them
run("MATCH (u:Unit)-[r:PART_OF]->(:Unit {name: 'Acme'}) "
    "RETURN u.name AS unit, r.inferred_by AS rule ORDER BY unit", g)
# [{'unit': 'Core Platform', 'rule': 'transitive_PART_OF'}, {'unit': 'Engineering', 'rule': None}]
```

### 3. Use it in an application

[`examples/integration_demo/`](https://github.com/qasimmughal03/gql-core/tree/main/examples/integration_demo)
is a small impact-analysis application that installs GQL-Core from PyPI. It loads a service
graph, derives indirect dependencies with their provenance, and answers "what breaks if the
database fails, and who owns it?":

```text
$ python app.py --failed db
If 'db' fails, these services are affected:
  Mobile BFF     tier 1  indirect  owner: Frontend
  Storefront     tier 1  indirect  owner: Frontend
  Auth API       tier 2  direct    owner: Identity
  Orders API     tier 2  direct    owner: Checkout
  Payments API   tier 2  indirect  owner: Payments
```

With a model, the same graph answers questions in plain English:

```python
from gql_core import ask

def llm(prompt: str) -> str:   # any model: a function from prompt text to query text
    return my_client.generate(prompt)

out = ask(graph, "Which services does the Payments team own?", client=llm, explain=True)
out["results"]    # rows from GQL-Core
out["attempts"]   # per attempt: the model's query, what was repaired, the query run, any feedback
```

Pass `correct_directions=False` or `max_retries=0` to turn the checks off. Without a `client`,
`ask()` uses a local Ollama server. The demo includes a ten-line Gemini client.

More runnable examples: [typed query plans](https://github.com/qasimmughal03/gql-core/blob/main/examples/example_b_typed_plan.py),
[inference rules](https://github.com/qasimmughal03/gql-core/blob/main/examples/example_c_ontology_inference.py),
and domain programs for [legal](https://github.com/qasimmughal03/gql-core/blob/main/examples/domains/legal_kg.py),
[software supply chain](https://github.com/qasimmughal03/gql-core/blob/main/examples/domains/software_supply_chain.py) and
[biomedical](https://github.com/qasimmughal03/gql-core/blob/main/examples/domains/biomedical_network.py) graphs.

### Command line

```bash
gql-core query --data examples/sample_graph.json \
  "MATCH (p:Person) RETURN p.name AS name ORDER BY name ASC"
```

Commands: `query`, `ask`, `validate`, `ingest`, `mirror`, `benchmark`, `version`
(`gql-core --help`).

## Architecture

```text
Cypher text ──► parser (Lark grammar) ──► AST ──► semantic checks ──► planner ──► executor ─┐
PlanBuilder ──► typed logical plan ──► validator ──► physical operators ───────────────────┤
                                                                                           ▼
Inference rules ──► fixed-point engine ──► derived facts (with provenance) ──► PropertyGraph
Question ──► model ──► query ──► direction / value repair ──► run ──► feedback ──► retry once
```

| Module | Purpose |
| --- | --- |
| `gql_core/graph.py` | `PropertyGraph`, `Node`, `Edge`, `Path`, loaders (`from_records`, `from_dict`, `from_networkx`) |
| `gql_core/query/` | Grammar, parser, semantic checks, planner and executor for Cypher text; direction and value repair |
| `gql_core/ir.py`, `builder.py` | Typed expressions, logical operators, `PlanBuilder` |
| `gql_core/physical/` | Expression evaluation and physical operators for typed plans |
| `gql_core/ontology/`, `inference/` | Typed ontology schemas and rule-based inference |
| `gql_core/ai.py`, `nl.py` | `ask()`, `translate_to_gql()`, repair and execution feedback |

Details: [system architecture](https://github.com/qasimmughal03/gql-core/blob/main/docs/SYSTEM_ARCHITECTURE.md),
[typed query API](https://github.com/qasimmughal03/gql-core/blob/main/docs/TYPED_QUERY_API.md),
[inference](https://github.com/qasimmughal03/gql-core/blob/main/docs/INFERENCE_ENGINE.md).

## Benchmarks

Every number comes from a **published benchmark** run with its own data, gold answers and
official metric, or, where marked, from a check against independently computed ground truth.
Nothing is scored against hand-written expected values.

### The engine: does GQL-Core return the right answer?

These measure GQL-Core alone: a fixed query goes in, and its result is compared with the
reference.

| Benchmark | What is checked | Result |
| --- | --- | ---: |
| [openCypher TCK](https://github.com/opencypher/openCypher) `2024.3` | Language conformance scenarios: results, errors and side effects | **3,879 / 3,879** supported scenarios pass (18 explicitly excluded of 3,897) |
| [CypherBench](https://huggingface.co/datasets/megagonlabs/cypherbench) test split ([paper](https://arxiv.org/abs/2412.18702)), measured at commit `43cab07` | All 2,348 gold Cypher queries run on GQL-Core over 7 Wikidata-derived graphs (up to 885k nodes and 1.9M relationships), compared with the answers **Neo4j** produced, with the official execution-accuracy metric | **98.21%** (2,306 / 2,348); **100%** when rows that differ only in the order of tied `ORDER BY` keys count as matches |
| [LDBC SNB](https://ldbcouncil.org/benchmarks/snb/) SF0.1 (unaudited) | Official query parameter cases on a 327,588-node, 1,477,965-relationship graph | **4 / 4** across 2 official query types |
| Hetionet v1.0 (our own check, not a published benchmark) | 5 Cypher queries and one rule on real biomedical data, each compared with an independent plain-Python computation | **6 / 6** agree; 27,498 derived facts equal the independent join |
| Test suite | Unit and regression tests | **394 / 394** |

On CypherBench there were no errors and no timeouts (120 s limit, as in the official
evaluation). All 42 official failures are `ORDER BY` queries whose tied rows come back in a
different order from Neo4j's. openCypher leaves that order undefined, but the official metric
counts it as a failure, so both numbers are reported.

### Domain evaluations: question in, answer out

These are **end-to-end results of a pipeline**: a language model (Gemini 2.5 Flash) writes the
query, and GQL-Core repairs and runs it. They depend on the model and the prompt as much as on
GQL-Core, and are reported in three configurations so each part's contribution is visible:

- **Model only:** the model's query runs exactly as written, from each benchmark's zero-shot prompt.
- **+ direction correction:** the same queries, with relationship directions the schema forbids reversed.
- **GQL-Core pipeline:** everything `ask()` does: stored-value hints in the prompt, direction and
  value repair, and one retry with execution feedback.

| Benchmark (metric) | Sample | Model only | + direction correction | **Pipeline** |
| --- | --- | ---: | ---: | ---: |
| [CypherBench](https://huggingface.co/datasets/megagonlabs/cypherbench), 7 graphs (execution accuracy) | 210 of 2,348 | 61.4% | 66.2% | **73.3%** |
| [MetaQA](https://github.com/yuyuz/MetaQA) 1-hop (exact match) | 100 of 9,947 | 69% | 88% | **88%** |
| MetaQA 2-hop | 100 of 14,872 | 40% | 100% | **100%** |
| MetaQA 3-hop | 100 of 14,274 | 52% | 80% | **86%** |
| MetaQA, all | 300 | 53.7% | 89.3% | **91.3%** |

Engine `0.2.0a3`; CypherBench at commit `afce555`, MetaQA at `67cd6f8`; seeded samples (seed 0),
temperature 0, thinking off. No step sees a gold query or answer. The pipeline was developed on
a disjoint seeded sample (CypherBench 78.1%, MetaQA 92.3%) and run once on this one.

Most remaining MetaQA misses come from the dataset: its knowledge base merges different films
that share a title. Most remaining CypherBench misses are a different reading of the question
from the gold query's. Every question, with the expected answer, each configuration's query and
answer, and the reason for each miss, is in
[`gemini_nl_benchmark_answers.xlsx`](https://github.com/qasimmughal03/gql-core/blob/main/benchmark/results/gemini_nl_benchmark_answers.xlsx).
Methodology, per-graph results and failure analysis:
[docs/NL_BENCHMARKS.md](https://github.com/qasimmughal03/gql-core/blob/main/docs/NL_BENCHMARKS.md).

### Reproduce

Datasets are downloaded on demand and are not part of the package.

```bash
git clone https://github.com/qasimmughal03/gql-core.git
cd gql-core
python -m pip install -e ".[dev,benchmark]"
python -m benchmark.tck.runner                                    # openCypher TCK
python -m benchmark.cypherbench.download
PYTHONHASHSEED=0 python -m benchmark.cypherbench.run_engine_parity # engine vs Neo4j gold answers
export GEMINI_API_KEY=...                                         # domain evaluations
python -m benchmark.cypherbench.run_nl2cypher --provider gemini --model gemini-2.5-flash --per-graph 30 --pipeline
python -m benchmark.metaqa.run_nl2cypher --provider gemini --model gemini-2.5-flash --per-hop 100 --pipeline
```

Drop `--pipeline` for the model-only numbers, or use `--correct-directions` for direction
correction alone. `--provider ollama --model <tag>` runs a local model instead.

## Limitations

- **Alpha.** APIs can change between `0.x` releases.
- **In memory only.** No durability, transactions or distributed execution; concurrent writes
  need your own locking. The whole graph must fit in RAM.
- **A subset of Cypher.** Not an ISO/IEC 39075 (GQL) implementation and not certified
  openCypher. `EXISTS { MATCH … }` supports a single pattern; other unsupported forms raise
  `UnsupportedFeature` rather than answer wrongly. See the
  [supported query contract](https://github.com/qasimmughal03/gql-core/blob/main/docs/SUPPORTED_QUERY_CONTRACT.md).
  The text and typed-plan APIs do not have identical coverage.
- **`ask()` needs a model** and is only as good as the model's reading of the question: about
  one CypherBench question in four is still answered wrongly with the full pipeline.
- **Benchmark scope.** Results are for the stated versions, samples and harnesses. The LDBC run
  is unaudited and covers a small read-query subset. The domain programs in `examples/domains/`
  are illustrations on small hand-built graphs, not accuracy evidence.

## Development

```bash
python -m pip install -e ".[dev,benchmark]"
python -m pytest tests/
python -m build && python -m twine check dist/*
```

See [CONTRIBUTING.md](https://github.com/qasimmughal03/gql-core/blob/main/CONTRIBUTING.md)
for the branch, test and release process, and [CHANGELOG.md](https://github.com/qasimmughal03/gql-core/blob/main/CHANGELOG.md)
for what changed in each version.

## Documentation

- [Quickstart walkthrough](https://github.com/qasimmughal03/gql-core/blob/main/docs/QUICKSTART.md)
- [Python API reference](https://github.com/qasimmughal03/gql-core/blob/main/docs/API_REFERENCE.md)
- [Supported query contract](https://github.com/qasimmughal03/gql-core/blob/main/docs/SUPPORTED_QUERY_CONTRACT.md)
- [Typed query API](https://github.com/qasimmughal03/gql-core/blob/main/docs/TYPED_QUERY_API.md) · [Logical operators](https://github.com/qasimmughal03/gql-core/blob/main/docs/LOGICAL_OPERATOR_SPEC.md)
- [Ontology and inference](https://github.com/qasimmughal03/gql-core/blob/main/docs/INFERENCE_ENGINE.md)
- [Domain evaluations (CypherBench, MetaQA)](https://github.com/qasimmughal03/gql-core/blob/main/docs/NL_BENCHMARKS.md) · [TCK analysis](https://github.com/qasimmughal03/gql-core/blob/main/docs/TCK_FAILURE_ANALYSIS.md) · [Release correctness report](https://github.com/qasimmughal03/gql-core/blob/main/docs/RELEASE_CORRECTNESS_REPORT.md)
- Release notes: [0.2.0a3](https://github.com/qasimmughal03/gql-core/blob/main/docs/RELEASE_NOTES_0.2.0a3.md) · [0.2.0a2](https://github.com/qasimmughal03/gql-core/blob/main/docs/RELEASE_NOTES_0.2.0a2.md) · [0.2.0a1](https://github.com/qasimmughal03/gql-core/blob/main/docs/RELEASE_NOTES_0.2.0a1.md)

## Citation and license

If you use GQL-Core in research, cite it with [CITATION.cff](https://github.com/qasimmughal03/gql-core/blob/main/CITATION.cff).

[Apache License 2.0](https://github.com/qasimmughal03/gql-core/blob/main/LICENSE).
GQL-Core is an independent project. Referencing ISO, openCypher, Neo4j, LDBC or Google does not
imply affiliation or certification.
