# Public Release Plan — Version 0.2.0

**Target Version:** `v0.2.0` (First Independent Public Release)  
**Release Name:** `gql-core` / `cricket-kg` Core Release  
**Maintainer:** Open-Source Maintenance Lead  
**Document Status:** Release Specification  

---

## 1. Smallest Meaningful Public Release Definition

The objective of `v0.2.0` is to deliver an **independently useful, technically credible, embeddable Python Property Graph engine with GQL-Core query execution and shape validation**, validated on both the Pakistan cricket corpus and an industry-standard graph benchmark.

It will NOT claim to be a distributed database or a full ISO GQL enterprise replacement. Its release boundary is strictly defined as an in-process, zero-daemon graph query and analysis engine.

---

## 2. Scope Boundaries: Core vs. Deferred Features

### Core Features Required for v0.2.0
1. **Core Graph Data Structure (`graph.store`):**
   - In-memory `PropertyGraph`, `Node`, `Edge`.
   - Forward and backward adjacency lookups.
   - Idempotent upserts and property merging.
   - Label-based scanning.
2. **Zero-Friction Ingestion Adapters:**
   - `PropertyGraph.from_networkx(G)` — instant GQL querying over any existing NetworkX graph.
   - `PropertyGraph.from_edges(...)` — direct creation from edge tuples `(src, dst)`.
   - `PropertyGraph.from_records(...)` — JSON/dictionary list ingestion.
   - Eliminates the "data reshaping tax" for arbitrary user graphs.
3. **Pluggable & Dynamic Schema Validation:**
   - Decouple `query/semantic.py` from hardcoded cricket `shapes.yaml`.
   - Support schema-free execution (open world) or dynamically inferred schema from loaded graph.
   - Optional SHACL shape validation when a custom `shapes.yaml` is provided.
4. **Formal GQL-Core Query Engine (`query`):**
   - EBNF Lark grammar supporting `MATCH ... WHERE ... RETURN`.
   - Directed and undirected relationship patterns.
   - Regular path queries (RPQ) with quantifiers `*`, `+`, `*N`, `*M..N`.
   - Full boolean expression trees (`AND`, `OR`, `NOT`, comparisons).
   - Aggregations (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`), aliases, multi-column `ORDER BY`, and `LIMIT`.
   - Pushdown planning and BFS-based plan executor with target deduplication.
5. **Standard Benchmark Integration:**
   - Implementation of a recognized benchmark adapter: a standardized **LDBC Social Network Benchmark (SNB) Micro-Workload** (or standard Transitive Closure/RPQ benchmark from database literature) to scientifically evaluate path reachability, undirected hops, and join expressibility on non-cricket data.
6. **Domain Showcase & Regression Oracles:**
   - Pakistan cricket corpus and test fixtures maintained as a real-world scale and correctness benchmark (Q1–Q5, LR1–LR5, NQ01–NQ35).
7. **Cross-Platform CLI Entrypoints:**
   - `gql-core query` (or `cricket-kg-query`): Execute GQL queries from CLI against any loaded graph.
   - `gql-core bench`: Run cross-engine verification benchmarks.


### Features Explicitly Deferred to v0.3.0+
1. **Disk-backed Storage / Persistence:** In-memory is sufficient for v0.2.0; persistence backends (e.g., LMDB, SQLite key-value, or Arrow serialization) are deferred to v0.3.0.
2. **`WITH` Clause Chaining:** Multi-clause query piping is deferred.
3. **`DISTINCT` Keyword:** Deduplication is currently handled implicitly at RPQ target level; explicit `RETURN DISTINCT` keyword grammar support is deferred to v0.2.1.
4. **Ollama LLM Translation Service:** The 100-query LLM harness (`run_suite_benchmark.py` and `nl_to_gql.py`) will be quarantined as an optional experimental tool under `tools/` or `contrib/` rather than a core release component.

---

## 3. Technical Credibility: Known Standard Benchmark Strategy

To satisfy peer review and open-source database credibility, the project cannot rely solely on hand-crafted queries over a cricket dataset. The v0.2.0 release must incorporate a **recognized standard benchmark**.

### Selected Benchmark: LDBC SNB (Interactive Micro-Workload)
The **Linked Data Benchmark Council Social Network Benchmark (LDBC SNB)** is the de facto industry standard for graph database query performance and expressibility.

#### Concrete Implementation Plan for v0.2.0:
1. **Workload Selection:**
   Implement a subset of the **LDBC SNB Interactive Read Workload** that directly tests graph-native operations:
   - **IS1 (Interactive Short 1):** Profile of a person + 1-hop organization and city traversal.
   - **IS2 (Interactive Short 2):** Recent messages of a person (1-hop traversal + format/date ordering).
   - **IS3 (Interactive Short 3):** Friends of a person (undirected `KNOWS` edge traversal).
   - **Transitive Reachability (RPQ / Bounded Kleene):** Friends-of-friends (`[:KNOWS*1..2]`) and path reachability across the social graph.
2. **Dataset:**
   Use the official LDBC SNB Data Generator (Datagen) at scale factor `SF 0.01` and `SF 0.1` (lightweight, deterministically generated social networks with Persons, Messages, Tags, and Forums).
3. **Evaluation Metric:**
   - GQL-Core token count vs SQL token count (expressibility ratio).
   - Correctness against SQLite relational mirror.
   - Traversal latency (median and p95 ms).

This establishes indisputable technical evidence that the engine's query model and RPQ traversals outperform relational SQL across standard computer science workloads, completely independent of the cricket domain.

---

## 4. Release Criteria & Quality Gates

### Correctness & Test Pass Criteria
- **100% Pass Rate:** All 226 existing unit tests plus new benchmark adapter tests must pass cleanly.
- **Coverage Threshold:** Minimum **85%** overall statement coverage across the repository, with **≥90%** coverage in `graph/`, `ingestion/validator.py`, and `query/`.
- **Row-Set Oracle Parity:** 100% exact row-set parity between GQL-Core and the relational mirror across all benchmark queries (Q1–Q5, LR1–LR5, NQ01–NQ35, and LDBC micro-queries).

### Platform Portability & Environment Criteria
- **Multi-OS CI Matrix:** Automated GitHub Actions workflows running on:
  - Ubuntu Latest (Linux)
  - macOS Latest
  - Windows Server / Windows 11
- **Python Compatibility:** Python 3.11, 3.12, 3.13, and 3.14.
- **Console & Encoding Safety:** Strict UTF-8 console output; fallback ASCII formatting on consoles that cannot render unicode symbols (resolving `UnicodeEncodeError` on Windows `cp1252`).
- **Signal Handling Safety:** Replace POSIX-only `signal.SIGALRM` with cross-platform threading timeouts (`concurrent.futures.ThreadPoolExecutor` or `threading.Timer`).

### Packaging & Distribution
- **Build Backend:** Modern `pyproject.toml` using `setuptools>=68` or `flit_core`.
- **Namespace Consolidation:** Consolidate top-level packages (`graph`, `query`, `ingestion`, `ontology`, `benchmark`) into a unified root package `cricket_kg` to avoid global site-packages collision.
- **Package Data Inclusions:** Explicitly include non-Python asset files (`package_data`: `grammar.lark`, `shapes.yaml`) so wheels do not raise `FileNotFoundError` at runtime.
- **Resource Resolution:** Migrate filesystem traversal in `query/parser.py` and `query/semantic.py` to `importlib.resources` so assets resolve cleanly in zipped or installed wheels.
- **Console Scripts:** Register CLI commands under `[project.scripts]`:
  - `cricket-kg` — interactive and file query runner.
  - `cricket-kg-bench` — comparative verification harness vs SQLite mirror.
- **Zero Heavy Dependencies:** Runtime dependencies must remain lightweight: `lark`, `pyyaml`, `requests`. No compilation required (`pip install` takes < 5 seconds).


### License & Governance
- **License:** Permissive open-source license (**MIT License** or **Apache 2.0**).
- **Public Documentation:** Clean README stripped of academic job-application or master's program references, replaced with production-grade quickstarts, architecture diagrams, grammar specifications, and reproducible benchmark commands.

---

## 5. Documented Known Limitations (v0.2.0)

Every release must honestly state what it cannot do:
1. **Captaincy Data Fidelity:** Cricsheet data lacks an official captaincy field; the parser's first-player heuristic is historically unreliable.
2. **In-Memory Volatility:** Data lives purely in RAM. Restarting the process requires re-ingesting JSON data or re-building from cached structures.
3. **Single-Clause Queries Only:** Subqueries and multi-clause `WITH` pipelines are not supported.
4. **RPQ Edge Variable Binding:** Variable-length paths (`*1..N`) cannot bind an edge variable for property inspection (raises `NotImplementedError`).
5. **No Mutation Query Syntax:** Mutations are performed via Python API (`add_node`, `add_edge`, `CricsheetParser`); GQL mutation statements (`CREATE`, `SET`, `DELETE`) are not parsed.
