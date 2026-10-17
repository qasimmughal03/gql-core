# Project Vision & Strategic Architecture

**Project Identity:** `gql-core` (Embeddable Python Property Graph & GQL Query Engine)  
**Document Status:** Approved Architecture Plan  
**Target Release:** v0.2.0 Domain-Agnostic Core Release  

---

## 1. The Core Purpose: A Universal, Zero-Friction Graph Engine

The core purpose of this project is to be a **general-purpose, embeddable, pure-Python Property Graph database and formal GQL query engine for ANY graph data**.

Previously, the repository was framed around a specific cricket dataset (`cricket-kg`). This created an artificial boundary: users who had graph data (social networks, knowledge graphs, dependency trees, financial transactions, biology networks) perceived the project as a sports statistics tool. Furthermore, requiring users to manually map their data into custom node/edge formats created an unnecessary barrier to adoption ("an extra step").

### The Realignment:
1. **Domain-Agnostic Engine:** The core system is **`gql-core`** — an embeddable, pure-Python graph engine supporting ISO/IEC 39075:2024 GQL-Core (`MATCH ... WHERE ... RETURN`), regular path queries (RPQ), and optional SHACL-style shape validation.
2. **Zero-Friction Ingestion:** Anyone with existing graph data can immediately query it using GQL without writing custom conversion scripts. Direct adapters are provided for:
   - **NetworkX graphs** (`PropertyGraph.from_networkx(G)`)
   - **Edge lists and tuples** (`PropertyGraph.from_edges([(src, dst, type), ...])`)
   - **Raw dictionaries / JSON** (`PropertyGraph.from_dict({"nodes": [...], "edges": [...]})`)
   - **Tabular DataFrames / CSVs** (`PropertyGraph.from_tables(nodes_df, edges_df)`)
3. **Decoupled Validation:** Schema and shape constraints are **optional and user-defined**. If no schema is specified, the engine operates schema-free or infers properties dynamically from the graph, rather than forcing a hardcoded domain schema.
4. **Cricket as a Benchmark Showcase:** The Pakistan cricket corpus (712K nodes, 1.47M edges) and test fixtures are repositioned as an **example workload and comparative SQL benchmark**, proving real-world scale and correctness rather than defining the library's identity.

---

## 2. The Actual Problem

Analyzing graph-structured data in Python forces developers into an unappealing compromise:

1. **NetworkX:** Excellent algorithms, but **has no declarative query language**. Writing path traversals, multi-hop joins, or aggregations requires imperative Python loops, nested comprehensions, and manual filtering.
2. **SQLite / Relational SQL:** Zero-daemon and easy to embed, but **terrible for path reachability and undirected traversals**, requiring dozens of lines of recursive `WITH RECURSIVE` CTEs and canonical `UNION ALL` statements.
3. **Neo4j / Memgraph:** Full declarative Cypher/GQL, but **requires external server daemons, Docker containers, JVM or C++ builds, and network overhead**. Too heavy for simple scripts, data science notebooks, unit tests, or embedded tools.
4. **The "Data Reshaping Tax":** Existing tools force developers to rewrite their graph structures to fit rigid proprietary schemas before they can even run a single query.

### The Solution: `gql-core`
A zero-daemon, pure-Python library that lets anyone take any graph (from NetworkX, JSON, CSV, or dictionaries) and run standard GQL queries with regular path expressions in two lines of code:

```python
import gql_core as gql
import networkx as nx

# 1. Take ANY existing graph (e.g., NetworkX)
G = nx.erdos_renyi_graph(100, 0.05)

# 2. Wrap it with zero boilerplate
graph = gql.PropertyGraph.from_networkx(G)

# 3. Query it with standard GQL / RPQ
results = gql.query("MATCH (a)-[:CONNECTED_TO*1..3]->(b) RETURN a, b", graph)
```

---

## 3. Intended Users & Personas

1. **NetworkX & Python Graph Practitioners:**  
   Developers who already use NetworkX or simple edge lists and want a declarative query language (`MATCH ... WHERE ... RETURN`) instead of writing complex traversal algorithms by hand.
2. **Data Scientists & Data Engineers:**  
   Analysts exploring connected datasets (supply chains, fraud rings, organizational charts, dependency graphs) in Jupyter notebooks who need Cypher-style path queries without spinning up Dockerized Neo4j.
3. **Knowledge Graph & Ontology Engineers:**  
   Engineers building structured KGs who want the option to validate custom SHACL shapes prior to querying.
4. **AI & NLP Researchers:**  
   Researchers working on Text-to-Graph and Text-to-GQL translation who need a lightweight, formally specified, deterministic query execution oracle.

---

## 4. Differentiation from Existing Tools

| Dimension | `NetworkX` | `SQLite` / `DuckDB` | `Neo4j` / `Memgraph` | **`gql-core`** |
|---|---|---|---|---|
| **Primary Focus** | Algorithmic graph analysis | Relational tables | Enterprise graph database | Embeddable graph querying |
| **Declarative Querying** | None (imperative code) | Declarative SQL | Declarative Cypher/GQL | Declarative ISO GQL-Core |
| **Path Traversal (RPQ)** | Manual algorithm calls | Recursive CTEs (`WITH RECURSIVE`) | Native (`[:REL*1..N]`) | Native (`[:REL*1..N]`) via EBNF parser |
| **Ingestion Friction** | Low (dictionary/edges) | Medium (DDL tables) | High (CSV load, APOC, auth) | **Zero (direct NetworkX/dict/tuple ingest)** |
| **Schema Validation** | None | Rigid table DDL | Optional constraints | Optional, user-defined SHACL shapes |
| **Deployment Model** | Embedded library | Embedded library | Server daemon / container | Embedded library |

---

## 5. Architectural Decisions: What to Preserve vs. What to Decouple

### Preserved Core Strengths:
1. **Normative Lark EBNF Grammar:** The ISO GQL-Core specification in `query/grammar.lark` is completely domain-agnostic and will remain the foundation.
2. **Four-Stage Query Pipeline:** `Parse -> Semantic Check -> Logical Plan (Pushdown) -> Physical Execution (BFS/HashJoin)`.
3. **Idempotent In-Memory Store:** Fast, pure-Python dictionary storage with dual-direction adjacency indexing.
4. **Target-Deduplicated BFS Traversal:** Clean reachability semantics for bounded Kleene stars.

### Decoupled from Cricket:
1. **Decouple `query/semantic.py` from hardcoded `shapes.yaml`:**  
   *Current Flaw:* `query/semantic.py` hardcoded a path to cricket `shapes.yaml`.  
   *Fix:* Semantic validation must inspect the active `PropertyGraph` schema dynamically, or accept an optional user-defined shape schema.
2. **Reposition `ingestion/cricsheet_parser.py`:**  
   Move cricket ingestion to `examples/cricket/` or an optional extension module `gql_core.datasets.cricket`.
3. **Generalize Benchmarking:**  
   Introduce standard domain-agnostic benchmarks (**LDBC Social Network Benchmark Micro-Workload**) alongside the cricket benchmark.

---

## 6. What Should Deliberately NOT Be Built

- **Do NOT build a heavy distributed database:** Keep it embedded and lightweight.
- **Do NOT require mandatory schema registration:** Users must be able to load an arbitrary graph and query it immediately without defining a schema first.
- **Do NOT implement non-core ISO GQL features:** Keep focused on `MATCH ... WHERE ... RETURN` with RPQ, aggregations, ordering, and limits.
- **Do NOT lock users into proprietary data formats:** Interoperability with NetworkX, Pandas, and JSON is the top priority.
