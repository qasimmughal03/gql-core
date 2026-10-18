# GQL-Core: Generic Property-Graph Query Engine

A formally-specified, Lark-parsed subset of [ISO/IEC 39075:2024 (GQL)](https://www.iso.org/standard/76120.html) with SHACL-style validation — now domain-agnostic. Bring your own graph and ontology, or use the bundled cricket knowledge graph as a worked example.

## Quickstart

```bash
git clone https://github.com/qasimmughal03/knowledge-graoh-with-formal-query.git
cd knowledge-graoh-with-formal-query
pip install -e .

# ── Generic: any graph ──
gql-core validate --schema my-shapes.yaml --data my-graph.json
gql-core query --schema my-shapes.yaml --data my-graph.json "MATCH (n) RETURN n"
gql-core benchmark --schema my-shapes.yaml --data my-graph.json --suite my-queries.yaml

# ── Cricket example ──
gql-core validate --schema examples/cricket/shapes.yaml --data tests/fixtures/
gql-core query --schema examples/cricket/shapes.yaml --data tests/fixtures/ \
  "MATCH (p:Player) RETURN p.name AS player ORDER BY player ASC LIMIT 5"
```

## Architecture

```
User's graph JSON ──► GraphIngester ──► PropertyGraph ──► Query Engine ──► Benchmark
User's shapes.yaml ──► ShapeValidator         │              │
                                               │              └─ Lark grammar (GQL-Core)
                                               └─ Generic SQLite Mirror
```

- **`gql_core/`** — the pip-installable generic engine
- **`examples/cricket/`** — Pakistan international cricket (preserved as demo, see [its README](examples/cricket/README.md))

## Graph Format (gql-graph-json)

```json
{
  "nodes": [
    {"@id": "alice", "@type": "Person", "name": "Alice", "age": 30},
    {"@id": "nyc", "@type": "City", "name": "New York", "country": "US"}
  ],
  "edges": [
    {"@type": "KNOWS", "@src": "alice", "@dst": "bob", "since": 2019},
    {"@type": "LIVES_IN", "@src": "alice", "@dst": "nyc"}
  ]
}
```

- `@id` on nodes is required and unique; on edges it's optional (auto-generated)
- `@type` is the node/edge label — must match a label in `shapes.yaml`
- `@src` / `@dst` reference node `@id`s
- All other keys become properties

## Schema (shapes.yaml)

```yaml
nodes:
  Person:
    required: [id, name]
    optional: [age, city]
    types:
      id: str
      name: str
      age: int
      city: str

edges:
  KNOWS:
    src: Person
    dst: Person
    undirected: true
    properties:
      since: int
```

See `examples/cricket/shapes.yaml` for the full cricket ontology (7 node types, 9 edge types).

## Benchmark Suites (YAML)

```yaml
name: my-benchmark
queries:
  - name: count_people
    gql: "MATCH (p:Person) RETURN COUNT(p) AS count"
    sql: "SELECT COUNT(*) AS count FROM person"   # optional
    expected:                                      # optional ground truth
      - count: 42
    key_columns: ["count"]
```

Three scoring modes:
- `expected` present → GQL vs expected answers (ground-truth oracle)
- `sql` present → GQL vs SQLite parity
- Neither → timing-only

## CLI Reference

| Command | Purpose |
|---|---|
| `gql-core validate --schema S --data D` | Validate graph against shapes |
| `gql-core ingest --schema S --data D` | Ingest graph, print stats |
| `gql-core query --schema S --data D "..."` | Run a GQL-Core query |
| `gql-core ask --schema S --data D "..."` | Ask a natural language question |
| `gql-core mirror --schema S --data D --db out.db` | Build SQLite mirror |
| `gql-core benchmark --schema S --data D --suite Q.yaml` | Run benchmark suite |
| `gql-core version` | Print version |

## Query Language (GQL-Core)

A documented subset of ISO/IEC 39075:2024 (and openCypher read dialect):

- `MATCH` with comma-separated patterns, node labels `(var:Label)`, inline filters `{prop: value}`
- Directed `-[e:LABEL]->` / `<-[]-` and undirected `-[]-` edges
- RPQ quantifiers: `*` (1..∞), `+`, `*N`, `*M..N` with openCypher relationship trail semantics (no relationship instance may appear twice in a path; multiple paths to destination preserved)
- `WHERE` predicate logic with three-valued logic (3VL) null semantics (`AND`, `OR`, `NOT`, parentheses, comparisons `=`, `!=`, `<`, `>`, `<=`, `>=`)
- `RETURN` with aggregates `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, column aliasing `AS alias`
- `ORDER BY` (ASC/DESC, multi-column), `LIMIT`

Explicitly excluded: mutations (`CREATE`, `MERGE`, `DELETE`, `SET`, `REMOVE`), multi-clause piping (`WITH`, `UNWIND`), `RETURN DISTINCT`, path variable assignment (`p = ...`).

The Lark grammar at `gql_core/query/grammar.lark` is the normative spec.

## Python API & Adapters

```python
import gql_core
from gql_core import PropertyGraph, Node, Edge, ShapeValidator, GraphIngester, run_query

# 1. Zero-Friction Adapters:
# From NetworkX (preserves native int vs str node IDs and MultiGraph parallel edges)
import networkx as nx
G = nx.MultiDiGraph()
G.add_edge(1, 2, key="e1", label="FOLLOWS")
graph_nx = PropertyGraph.from_networkx(G)

# From Records (preserves int 0 and falsy properties, rejects duplicate collisions)
nodes = [{"id": 0, "label": "Person", "name": "Alice", "active": False}]
edges = [{"src": 0, "dst": 1, "label": "KNOWS"}]
graph_rec = PropertyGraph.from_records(nodes, edges)

# From Edge Tuples (pairs, triples, or 4-tuples with properties)
graph_edges = PropertyGraph.from_edges([(1, 2, "KNOWS", {"since": 2024})])

# 2. Query Execution:
rows = run_query(
    "MATCH (a:Person)-[:KNOWS]->(b) WHERE a.id = 0 RETURN b.name AS friend",
    graph_rec,
)

# 3. Natural Language Interface:
result = gql_core.ask(graph_rec, "Who does Alice know?", client=None)
```

### Runtime Environment & Thread Safety

- **Supported Python Versions**: `Python >= 3.11`
- **Runtime Dependencies**: `lark>=1.2.2`, `pyyaml>=6.0.2`, `requests>=2.32.3`.
- **Thread Safety**: `PropertyGraph` is a pure in-memory store without internal locking. Concurrent reads are safe under standard CPython GIL semantics. Concurrent writes require external synchronization.

## Cricket Example

The full cricket knowledge graph is preserved at `examples/cricket/` — 7 node types, 9 edge types, 712K nodes on the full Pakistan corpus. See [examples/cricket/README.md](examples/cricket/README.md) for the domain-specific quickstart, ontology, and benchmark results.

### Cricket Benchmark Highlights

| Query | Purpose | Cypher (ms) | SQL (ms) | SQL/Cypher tokens |
|---|---:|---:|---:|
| Q1 | Top run scorers | 32.5 | 8.6 | 29 / 15 (1.9×) |
| Q2 | Best bowling at Karachi | 28.4 | 8.3 | 47 / 21 (2.2×) |
| **Q4** | Babar's frequent partners (undirected) | **0.6** | **16.6** | 68 / 20 (3.4×) |
| Q5 | Bounded RPQ `NEXT_DELIVERY*1..3` | 382.8 | 0.01 | 53 / 13 (4.1×) |
| LR2 | 2-hop teammates (undirected RPQ) | **2.3** | **1.9** | 108 / 15 (**7.2×**) |

## External Benchmarks & Compatibility Testing

GQL-Core integrates external industry-standard test suites to establish empirical correctness and execution metrics:

1. **openCypher TCK Compatibility Suite**: Evaluates compatibility against the official [openCypher TCK](https://github.com/opencypher/openCypher) pinned to release `2024.3`.
2. **LDBC SNB Interactive v1 Read-Only Benchmark**: Evaluates execution and answer correctness against official [LDBC SNB reference implementations](https://github.com/ldbc/ldbc_snb_interactive_v1_impls) using the official static initial dataset.

### Reproduction Commands

```bash
# 1. Clone pinned upstream corpora into cache:
git clone --depth 1 --branch 2024.3 https://github.com/opencypher/openCypher.git benchmark/cache/openCypher
git clone --depth 1 https://github.com/ldbc/ldbc_snb_interactive_v1_impls.git benchmark/cache/ldbc_snb_impls

# 2. Run openCypher TCK compatibility runner:
python -m benchmark.tck.runner

# 3. Run LDBC SNB Interactive v1 benchmark (with answer oracle verification):
python -m benchmark.snb.runner

# 4. Run CI benchmark smoke tests:
python -m pytest tests/test_benchmark_smoke.py
```

See [docs/RELEASE_VERIFICATION_REPORT.md](docs/RELEASE_VERIFICATION_REPORT.md) for the full evidence report, including classification taxonomy, latency distributions, and answer oracle validation.

## References

- ISO/IEC 39075:2024 — Graph Query Language ([standard](https://www.iso.org/standard/76120.html))
- W3C SHACL — Shapes Constraint Language ([recommendation](https://www.w3.org/TR/shacl/))
- Lark parsing library ([docs](https://lark-parser.readthedocs.io/))

