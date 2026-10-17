# Engineering Roadmap & Prioritized Execution Plan

**Project:** `cricket-kg` / `gql-core`  
**Document Status:** Normative Implementation Roadmap  
**Target Horizon:** v0.2.0 (Release Blocker Phase) through v0.4.0 (Persistence & Standards)  

---

## 1. Development Milestones & Strategic Horizon

```
[v0.2.0 - Stable Core Release]
   ├── P0: Resolve Windows encoding & signal crashes
   ├── P0: Clean package packaging, entrypoints & documentation
   ├── P0: Restore missing benchmark artifacts
   └── P1: Standard Industry Benchmark (LDBC SNB Micro-Workload)
         │
         ▼
[v0.3.0 - Query Expressibility & Quality of Life]
   ├── P1: Grammar support for `DISTINCT` in projections and aggregations
   ├── P1: Relationship variable binding on multi-hop RPQs (relationship list)
   ├── P1: Property indexing on common filter attributes
   └── P1: Formalized Python public query API
         │
         ▼
[v0.4.0 - Persistence & Extensibility]
   ├── P2: Pluggable storage backend (SQLite KV / LMDB / DuckDB storage engine)
   ├── P2: Multi-clause query piping (`WITH` clause)
   └── P2: General-purpose JSON/CSV tabular data ingestor
```

---

## 2. Known Architectural Risks & Mitigation Strategies

1. **Risk: Memory Growth on Large Graphs**
   - *Nature of Risk:* In-memory storage of 1M+ nodes using Python objects (`dict`, `dataclass`) consumes significant RAM and risks `MemoryError` in memory-constrained CI or containerized environments.
   - *Mitigation:* Preserve in-memory operation for graphs under 1M nodes; design a zero-copy or disk-backed storage engine interface for v0.4.0.
2. **Risk: In-Memory BFS Combinatorial Explosion**
   - *Nature of Risk:* Unbounded or high-depth Kleene star traversals on dense subgraphs (e.g., dense `TEAMMATES_WITH` cliques) can explore hundreds of thousands of paths.
   - *Mitigation:* The executor already enforces target-node deduplication during BFS (yielding nodes once at shortest depth), which prevents cyclic loops. A hard safety limit (`max_depth = 50` or `max_nodes = 500,000`) should be introduced in query planning.
3. **Risk: Disconnected LLM Translation Harness**
   - *Nature of Risk:* Shipping an untested Ollama client with hardcoded local service dependencies will cause immediate user friction and bug reports.
   - *Mitigation:* Decouple experimental LLM translation tools from the core package; place them under `tools/` with explicit optional dependency guards.

---

## 3. Prioritized Implementation Plan (P0 / P1 / P2)

---

### Phase 1: P0 — Immediate Release Blockers (Target: v0.2.0-rc1)

#### Task P0-1: Cross-Platform Windows Console Encoding Fix
- **Problem:** `benchmark/run_nl_benchmark.py` and `benchmark/run_suite_benchmark.py` crash with `UnicodeEncodeError` when executed on Windows systems using default code pages (`cp1252`), failing on characters `✓` (`\u2713`) and `→` (`\u2192`).
- **Evidence Supporting Need:** Verified during audit: `python -m benchmark.run_nl_benchmark --data tests/fixtures` crashed at line 241 with `UnicodeEncodeError: 'charmap' codec can't encode character '\u2713'`.
- **Exact Affected Subsystem:** `benchmark/run_nl_benchmark.py`, `benchmark/run_suite_benchmark.py`.
- **Proposed Solution:** Implement an encoding-safe output helper. Configure stdout to reconfigure encoding to UTF-8 (`sys.stdout.reconfigure(encoding='utf-8')` if available) and provide safe fallback ASCII indicators (`[OK]` instead of `✓`, `->` instead of `→`) when the console stream does not support unicode glyphs. Remove non-ASCII characters from module docstrings passed to `argparse`.
- **Acceptance Criteria:** `python -m benchmark.run_nl_benchmark --data tests/fixtures --iters 1` completes with return code 0 on Windows PowerShell without exceptions.
- **Required Tests:** End-to-end regression test invoking CLI runners under mock `cp1252` encoding.
- **Dependencies:** None.
- **Release Priority:** **P0** (Release Blocker).

---

#### Task P0-2: Replace POSIX-Only `SIGALRM` with Cross-Platform Timeout
- **Problem:** `benchmark/run_suite_benchmark.py` imports `signal` and invokes `signal.signal(signal.SIGALRM, ...)` and `signal.alarm(...)`. `SIGALRM` does not exist on Windows and raises `AttributeError: module 'signal' has no attribute 'SIGALRM'`.
- **Evidence Supporting Need:** Verified during audit: `hasattr(signal, 'SIGALRM') == False` on Windows Python 3.14.
- **Exact Affected Subsystem:** `benchmark/run_suite_benchmark.py` (lines 68–80).
- **Proposed Solution:** Replace `signal.alarm` with a cross-platform execution wrapper using `concurrent.futures.ThreadPoolExecutor(max_workers=1)` with a `future.result(timeout=timeout)` guard.
- **Acceptance Criteria:** Query execution timeout functions identically on Windows, Linux, and macOS without relying on POSIX signals.
- **Required Tests:** Unit test verifying timeout cancellation fires accurately on all operating systems.
- **Dependencies:** None.
- **Release Priority:** **P0** (Release Blocker).

---

#### Task P0-3: Package Manifest, Console Scripts & Documentation Cleanup
- **Problem:**
  1. `pyproject.toml` lacks console script entrypoints. Users must execute modules via `python -m ...` or run standalone scripts with manual paths.
  2. `README.md` contains outdated academic master's degree alignment sections ("TU Berlin / RWTH Aachen relevance") and references a missing benchmark artifact (`benchmark/results/suite_benchmark.json`).
- **Evidence Supporting Need:**
  - Audit verified `suite_benchmark.json` does not exist in the working tree or git history.
  - Users running `pip install .` do not receive any runnable CLI commands.
- **Exact Affected Subsystem:** `pyproject.toml`, `README.md`, `docs/`.
- **Proposed Solution:**
  1. Add `[project.scripts]` to `pyproject.toml`:
     - `cricket-kg = "ingestion.cricsheet_parser:main"`
     - `cricket-kg-bench = "benchmark.vs_sqlite:main"`
     - `cricket-kg-nlbench = "benchmark.run_nl_benchmark:main"`
  2. Strip academic/portfolio marketing text from `README.md`, replacing it with a production-grade open-source overview, clean API examples, and verified benchmark metrics.
  3. Correct the claim regarding `suite_benchmark.json` or generate and commit the baseline artifact.
- **Acceptance Criteria:** `pip install -e .` installs runnable entrypoints; `cricket-kg --help` and `cricket-kg-bench --help` execute cleanly; documentation is production-ready.
- **Required Tests:** Packaging installation test (`pip install -e .` in clean venv).
- **Dependencies:** Task P0-1.
- **Release Priority:** **P0** (Release Blocker).

---

#### Task P0-4: Decouple Semantic Validation from Hardcoded Cricket Schema
- **Problem:** `query/semantic.py` hardcodes `path = Path(__file__).resolve().parent.parent / "ontology" / "shapes.yaml"`. Any query referencing edge labels not present in cricket's `shapes.yaml` (e.g. `KNOWS`, `FRIENDS_WITH`, `CONNECTS_TO`) throws `SemanticError("Unknown edge label ...")`. This renders the engine incapable of querying ANY graph other than cricket!
- **Evidence Supporting Need:** Code inspection of `query/semantic.py` line 200: `if label not in _schema()["edge_shapes"]: raise SemanticError(...)`. Attempting to query an arbitrary graph fails.
- **Exact Affected Subsystem:** `query/semantic.py`, `query/executor.py`.
- **Proposed Solution:** Refactor `validate_query(query, schema=None, graph=None)`:
  1. If an explicit shape schema is provided, validate against it.
  2. If a `graph` is passed and no schema is provided, dynamically infer known labels and properties from `graph._edge_by_label.keys()`.
  3. If schema validation is disabled or schema is empty, run in open/schema-free mode (permitting any edge and node label).
- **Acceptance Criteria:** Queries over non-cricket graphs (e.g. `MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN a.name`) execute successfully without `SemanticError`.
- **Required Tests:** Unit tests querying arbitrary non-cricket graphs (social network, dependency graph) without a predefined `shapes.yaml`.
- **Dependencies:** None.
- **Release Priority:** **P0** (Release Blocker for General Use).

---

#### Task P0-5: Zero-Friction Graph Ingestion Adapters (`from_networkx`, `from_dicts`, `from_edges`)
- **Problem:** Currently, anyone with existing graph data (in NetworkX, dictionaries, edge lists, or CSVs) must write hundreds of lines of custom parsing code to instantiate internal `Node` and `Edge` objects. This "data reshaping tax" creates severe friction and deters adoption.
- **Evidence Supporting Need:** User directive: *"anyone who has to change their graph into something like property graph to use our system which i think creates an extra step, it should not be only for cricket it can be for anyone"*.
- **Exact Affected Subsystem:** `graph/store.py` (`PropertyGraph`).
- **Proposed Solution:** Add standard zero-friction classmethod constructors to `PropertyGraph`:
  1. `PropertyGraph.from_networkx(G, default_node_label="Node", default_edge_label="CONNECTED_TO")`: Convert any `nx.Graph` or `nx.DiGraph` directly, importing node/edge attributes as properties.
  2. `PropertyGraph.from_edges(edges, directed=True)`: Ingest a list of `(src, dst)` or `(src, dst, type, props)` tuples.
  3. `PropertyGraph.from_records(nodes=[...], edges=[...])`: Ingest standard JSON-like dictionaries of node/edge dictionaries.
  4. `PropertyGraph.from_tables(nodes_df, edges_df, ...)`: Convert pandas/polars DataFrames into a property graph.
- **Acceptance Criteria:** A user with a NetworkX graph or simple list of edge tuples can instantiate a `PropertyGraph` and execute a GQL query in 2 lines of Python.
- **Required Tests:** Comprehensive unit tests for `from_networkx`, `from_edges`, `from_records`, and `from_tables`.
- **Dependencies:** Task P0-4.
- **Release Priority:** **P0** (Release Blocker for General Use).


---

### Phase 2: P1 — Important Improvements & Technical Credibility (Target: v0.2.0 / v0.2.1)

#### Task P1-1: Standard Industry Benchmark Adapter (LDBC SNB Micro-Workload)
- **Problem:** All existing benchmarks are executed exclusively on an internal cricket dataset against custom SQLite queries. External database engineers and reviewers cannot verify whether the engine's expressibility and performance advantages generalize to standard graph problems.
- **Evidence Supporting Need:** User requirement: *"for this we also have to use some known benchmark to prove it"*. Industry standards mandate LDBC SNB for graph query credibility.
- **Exact Affected Subsystem:** `benchmark/ldbc/`, `benchmark/` test harness.
- **Proposed Solution:**
  1. Create a lightweight benchmark module (`benchmark/ldbc/`) that loads LDBC SNB Social Network data (Person, Knows, Message, Forum).
  2. Bundle a deterministic small-scale LDBC fixture dataset (generated at scale factor SF 0.001 / SF 0.01).
  3. Implement canonical LDBC Interactive Short queries in GQL-Core and SQL:
     - **IS1:** Person profile + university/company organization traversal.
     - **IS2:** Recent messages created by a person.
     - **IS3:** Friends of a person (undirected `KNOWS` traversal).
     - **IS-RPQ:** Bounded transitive closure of friends (`[:KNOWS*1..2]`).
  4. Compare token count, recursion requirement, and query latency against SQLite mirror.
- **Acceptance Criteria:** `python -m benchmark.ldbc` runs automatically in CI, proving expressibility reduction (≥2× token savings) and 100% row-set parity on standard LDBC data.
- **Required Tests:** Automated regression tests in `tests/test_ldbc_benchmark.py`.
- **Dependencies:** P0-1.
- **Release Priority:** **P1** (Technical Credibility Core).

---

#### Task P1-2: Grammar and Executor Support for `DISTINCT`
- **Problem:** The query language cannot parse or execute `RETURN DISTINCT p.country` or aggregations like `COUNT(DISTINCT p.id)`. Users must perform deduplication downstream in Python.
- **Evidence Supporting Need:** Documented in README as an out-of-scope v1 limitation; confirmed by Lark parse error on `MATCH (p:Player) RETURN DISTINCT p.country`.
- **Exact Affected Subsystem:** `query/grammar.lark`, `query/ast.py`, `query/parser.py`, `query/executor.py`.
- **Proposed Solution:**
  1. Add `DISTINCT?` token to `return_clause` and `agg_call` in `grammar.lark`.
  2. Extend `Projection` AST with a `distinct: bool` flag.
  3. In `query/executor.py`, apply row-level deduplication after projections when `distinct=True`, and apply value-set deduplication inside `COUNT` aggregation.
- **Acceptance Criteria:** `MATCH (p:Player) RETURN DISTINCT p.country` returns unique country codes; `COUNT(DISTINCT p.country)` returns unique count.
- **Required Tests:** Grammar tests in `test_parser_grammar.py` and executor tests in `test_executor.py`.
- **Dependencies:** None.
- **Release Priority:** **P1** (Core Expressibility).

---

#### Task P1-3: Multi-Hop RPQ Relationship List Binding
- **Problem:** Specifying an edge variable on a multi-hop pattern (e.g., `MATCH (a)-[r:NEXT_DELIVERY*1..3]->(b) RETURN r`) raises `NotImplementedError`. While preventing silent data corruption, it prevents users from inspecting paths.
- **Evidence Supporting Need:** Code in `query/executor.py` lines 122–127 explicitly raises `NotImplementedError`.
- **Exact Affected Subsystem:** `query/executor.py`.
- **Proposed Solution:** Update `_walk` and `_expand` to bind `new_row[op.edge_var] = edge_path` (as a `list[Edge]`) when path length is variable or > 1, matching Cypher specification. For single-hop patterns, retain single `Edge` binding for backwards compatibility.
- **Acceptance Criteria:** Bounded RPQs with edge variables return lists of traversed edges without raising exceptions.
- **Required Tests:** Unit tests in `test_executor.py` asserting properties across edge lists.
- **Dependencies:** None.
- **Release Priority:** **P1**.

---

### Phase 3: P2 — Future Enhancements & Persistence (Target: v0.3.0+)

#### Task P2-1: Pluggable Disk-Backed Storage Engine (SQLite / LMDB)
- **Problem:** All graph data is in-memory. Ingesting large corpuses requires a multi-minute cold start on every process invocation.
- **Evidence Supporting Need:** Ingesting 1,123 matches takes ~45 seconds on startup and consumes ~2GB of RAM.
- **Exact Affected Subsystem:** `graph/store.py`, `graph/storage/`.
- **Proposed Solution:** Introduce a storage interface (`BaseGraphStore`) with the current in-memory implementation as `MemoryGraphStore`, and implement a disk-backed `SQLiteKVGraphStore` or `DuckDBGraphStore` where nodes, edges, and adjacency sets are persisted in local files.
- **Acceptance Criteria:** A graph can be opened instantly from disk (`PropertyGraph.open("cricket.db")`) without re-parsing source JSON.
- **Dependencies:** P0 and P1 milestones complete.
- **Release Priority:** **P2** (Future Enhancement).

---

#### Task P2-2: Multi-Clause Query Chaining (`WITH` Clause)
- **Problem:** Queries cannot pipe intermediate results into subsequent pattern matches or aggregations (e.g., `MATCH ... WITH ... MATCH ...`).
- **Evidence Supporting Need:** Standard Cypher/GQL query pipelines rely on `WITH` for query modularity.
- **Exact Affected Subsystem:** `query/grammar.lark`, `query/planner.py`, `query/executor.py`.
- **Proposed Solution:** Extend grammar to support query clause chaining: `MATCH ... WHERE ... WITH ... MATCH ... RETURN ...`. The planner treats `WITH` as a projection barrier that feeds intermediate bindings into the subsequent match clause.
- **Acceptance Criteria:** Multi-stage queries execute and pass regression parity checks.
- **Dependencies:** Task P1-2.
- **Release Priority:** **P2**.

---

## 4. Execution Summary & Work Breakdown

| Task ID | Description | Subsystem | Priority | Est. Complexity |
|---|---|---|---|---|
| **P0-1** | Fix Windows console unicode encode crashes | `benchmark/` | **P0** | Low (0.5 day) |
| **P0-2** | Replace POSIX-only `SIGALRM` with cross-platform timeout | `benchmark/` | **P0** | Low (0.5 day) |
| **P0-3** | Packaging, console scripts, documentation cleanup | Root, `pyproject.toml` | **P0** | Low (0.5 day) |
| **P0-4** | Decouple semantic validation from hardcoded cricket schema | `query/semantic.py` | **P0** | Medium (1 day) |
| **P0-5** | Zero-friction ingestion adapters (`from_networkx`, `from_dicts`) | `graph/store.py` | **P0** | Medium (1 day) |
| **P1-1** | Implement LDBC SNB Micro-Benchmark adapter | `benchmark/ldbc/` | **P1** | Medium (2 days) |
| **P1-2** | Add `DISTINCT` keyword support to grammar & executor | `query/` | **P1** | Medium (1 day) |
| **P1-3** | Support relationship list binding on multi-hop RPQ | `query/executor.py` | **P1** | Low (1 day) |
| **P2-1** | Pluggable disk-backed storage engine | `graph/` | **P2** | High (1–2 weeks) |
| **P2-2** | Multi-clause query chaining (`WITH` clause) | `query/` | **P2** | High (1–2 weeks) |

---

## 5. Benchmark Architecture & End-of-Run Reporting Specification

To ensure rigorous scientific and engineering credibility, every benchmark execution must terminate with a deterministic, structured end-of-run protocol that verifies correctness, evaluates expressibility, measures latency distribution, and generates verifiable artifacts.

### 5.1. End-of-Run Terminal Output Specification
At the conclusion of each benchmark run, the harness must print a standardized, cross-platform ASCII/UTF-8 summary table displaying:

```text
========================================================================================================
BENCHMARK EXECUTION SUMMARY — GQL-Core vs. SQLite Mirror
  Timestamp: 2026-10-17T23:50:00 | Git Rev: adcc697 (clean) | Platform: win32 / Python 3.14.7
  Graph Size: 65 nodes / 112 edges (Fixture) | Iterations per query: 50
========================================================================================================
Query ID   Class             Cypher (ms)   SQL (ms)   Tokens (GQL/SQL)  Recursive SQL?  Parity  Status
--------------------------------------------------------------------------------------------------------
Q1         direct_lookup           0.418      0.074       15 / 29 (1.9x)       No        Match   [PASS]
Q2         filtered_join           0.380      0.082       21 / 47 (2.2x)       No        Match   [PASS]
Q3         group_aggregate         0.355      0.071       23 / 44 (1.9x)       No        Match   [PASS]
Q4         undirected_traversal    0.418      0.166       20 / 68 (3.4x)       No        Match   [PASS]
Q5         rpq_bounded_path        0.366      0.085       13 / 53 (4.1x)       YES       Match   [PASS]
LR1        conjunctive_pattern     0.679      0.067       24 / 49 (2.0x)       No        Match   [PASS]
LR2        transitive_closure      0.316      0.078       15 / 108 (7.2x)      YES       Match   [PASS]
LR3        threshold_constraint    0.694      0.062       25 / 44 (1.8x)       No        Match   [PASS]
LR4        path_composition        0.868      0.072       28 / 74 (2.6x)       No        Match   [PASS]
LR5        rpq_property_filter     0.381      0.079       14 / 55 (3.9x)       YES       Match   [PASS]
--------------------------------------------------------------------------------------------------------
AGGREGATE EVALUATION METRICS:
  Total Queries Evaluated    : 10
  Correctness Parity Rate    : 10 / 10 (100.0%) — Exact sorted row-set equality confirmed
  Geometric Mean Token Ratio : 2.84x SQL verbosity penalty over GQL-Core
  Max Expressibility Advantage: 7.2x (LR2 Transitive Closure — WITH RECURSIVE + CASE replacement)
  GQL Median Traversal Time  : 0.40 ms (prepared execution: 0.04 ms)
  SQL Median Traversal Time  : 0.08 ms
  Peak Memory RSS Delta      : +14.2 MB
  Overall Benchmark Status   : SUCCESS — ALL GATES PASSED
========================================================================================================
```

### 5.2. End-of-Run Machine-Readable Artifact Generation
At completion, the harness writes two immutable, version-controlled artifacts to `benchmark/results/`:

1. **`benchmark/results/<workload>_results.json`:**
   Complete JSON dump containing:
   - System metadata: CPU architecture, OS, Python version, memory, timestamp, exact git commit hash, and dirty status.
   - Graph metadata: Node count, edge count, label distributions.
   - Per-query microsecond metrics: Mean, median, p90, p95, p99, standard deviation, minimum, maximum across all iterations.
   - Breakdown of GQL cost: `cypher_parse_plan` time vs. `cypher_execute` time.
   - Expressibility stats: Token counts, recursion markers, AST depth.
   - Correctness confirmation: Boolean flag `result_correct: true`, row counts, and sample row hashes.

2. **`benchmark/results/LATEST_BENCHMARK_REPORT.md`:**
   Auto-generated markdown table formatted for inclusion in pull requests, project documentation, or research publications.

### 5.3. Automated CI Quality Gates (At the End of Run)
The benchmark script must exit with a non-zero code (`sys.exit(1)`) if any of the following quality gates fail:
- **Correctness Gate:** Any query where `result_correct == False` immediately triggers benchmark failure.
- **Regression Gate:** In CI mode (`--ci`), compare `cypher_execute.median_ms` against the baseline in `results.json`. If execution regresses by > 15% without explanation, flag a performance warning or failure.
- **Memory Safety Gate:** Confirm that resident set size (RSS) returns to baseline after garbage collection, preventing unbounded memory accumulation during multi-iteration stress tests.

### 5.4. Known Standard Benchmark Completion Criteria (LDBC SNB & GQLBench)
When running standard industry benchmarks, the end-of-run report must evaluate:
- **GQLBench Formal Grammar Coverage (`benchmark/gqlbench_eval.py`):**
  Evaluates GQL-Core against the 25,332 standardized query corpus from the GQLBench research benchmark, reporting grammar pass rates, supported feature coverage (RPQ, multi-hop, aggregations), and formal rejection categorization.
- **LDBC Social Network Benchmark (SNB Micro-Workload):**
  - **Interactive Short (IS1–IS3) Parity:** Verifying that 1-hop person-organization traversals and undirected `KNOWS` friend lookups match standard reference outputs.
  - **Transitive Closure (RPQ) Evaluation:** Evaluating `[:KNOWS*1..2]` and `[:KNOWS*1..3]` against recursive SQL CTEs to prove domain-independent expressibility and traversal efficiency.
  - **Throughput & Latency CDF:** Quantifying queries-per-second (QPS) and cumulative distribution functions (CDF) to demonstrate consistent sub-millisecond in-memory response times.
- **Unified Multi-Domain Benchmark (`examples/run_all_benchmarks.py`):**
  Runs 61 queries across 4 distinct domains (Cricket, Movies, Star Wars, and Social Networks), asserting 100% pass rates across all 9 query classes.

---

## 6. Benchmark Execution Protocol & Reproducibility Matrix

| Benchmark Suite | Data Source | Scale Factor / Size | Queries | Execution Command | Expected Outcome |
|---|---|---|---|---|---|
| **Multi-Domain Unified Benchmark** | `examples/` & `fixtures/` | Movies, Star Wars, Social, Cricket | 61 queries | `python examples/run_all_benchmarks.py --iters 30` | **61/61 PASS (100.0%)**, median 1.1ms |
| **GQLBench Grammar Coverage** | GQLBench Corpus | 25,332 queries | Formal grammar coverage | `python benchmark/gqlbench_eval.py` | Complete pass rate & rejection analysis |
| **Fixture Smoke Run** | `tests/fixtures/` | 65 nodes / 112 edges | 10 (Q1–Q5, LR1–LR5) | `python -m benchmark.vs_sqlite --data tests/fixtures --iters 5` | 10/10 PASS, < 5 seconds |
| **NL QA Fixture Run** | `tests/fixtures/` | 65 nodes / 112 edges | 35 (NQ01–NQ35) | `python -m benchmark.run_nl_benchmark --data tests/fixtures --iters 5` | 35/35 PASS, < 8 seconds |
| **Full Pakistan Corpus** | `data/pakistan/` | 712K nodes / 1.47M edges | 45 queries | `python -m benchmark.vs_sqlite --data data/pakistan --db data/cricket.db --iters 50` | 45/45 PASS, 1.8x–7.2x token advantage |
| **LDBC SNB Micro-Workload** | `benchmark/ldbc/data/` | SF 0.01 / ~10K nodes | 5 canonical queries | `python -m benchmark.ldbc.run --iters 50` | 5/5 PASS, domain-independent proof |



