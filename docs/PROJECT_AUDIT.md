# Engineering Audit & Codebase Assessment

**Repository:** `cricket-kg` (Property Graph + Formal Query Engine)  
**Assessed Version / Git Rev:** `adcc697` (Branch: `feat/implementation`)  
**Auditor:** Principal Software Engineer, Systems Architect & Open-Source Maintainer  
**Date:** October 2026  
**Environment Evaluated:** Windows 11, Python 3.14.7, pytest 8.4.2  

---

## 1. Executive Summary

This repository contains an embeddable, pure-Python Property Graph Database and formally-specified query engine implementing a documented subset of **ISO/IEC 39075:2024 (GQL-Core)**, coupled with **W3C SHACL-inspired shape validation** and an automated comparative benchmark mirror against SQLite.

The repository is substantially more advanced and technically rigorous than a typical portfolio demonstration:
- It contains a fully operational parser based on Lark EBNF grammars for GQL-Core (`MATCH ... WHERE ... RETURN` with regular path queries and aggregations).
- It incorporates a logical query planner with pushdown predicates and hash joins.
- It includes an in-memory property graph store with dual-adjacency indexing and idempotent mutations.
- It features an automated SHACL-style schema validator enforcing type, pattern, enum, and numerical constraints before insertion.
- It is backed by a suite of 226 automated tests passing in ~15 seconds with 81% overall statement coverage (and 87–100% coverage across core engine modules).

However, to transition from an academic/portfolio artifact into a **technically credible, independently releasable open-source system**, the project must resolve several architectural liabilities, platform-specific runtime defects, benchmark scope limitations, and branding misalignments. Specifically:
1. **Benchmark Rigor & Standardization:** Current claims rely exclusively on an internal custom dataset (Pakistan cricket matches from cricsheet.org) comparing GQL-Core against hand-crafted SQLite queries. To establish technical credibility in the database and knowledge graph communities, the engine must be evaluated against **standard, recognized benchmarks** (e.g., an LDBC SNB micro-benchmark or standardized RPQ transitive closure workloads).
2. **Platform Compatibility & Defect Isolation:** Multiple benchmark scripts fail on Windows due to POSIX-only signals (`signal.SIGALRM`), console character encoding errors (`UnicodeEncodeError` under `cp1252` with unicode glyphs `✓` and `→`), and missing benchmark result artifacts referenced in documentation.
3. **Core Engine Omissions:** Fundamental query keywords expected in basic graph analysis (such as `DISTINCT`, `WITH`, and relationship property access during multi-hop RPQs) are either rejected or raise runtime exceptions.
4. **Packaging & Interface Stability:** The package lacks clean CLI console scripts, has no persistence layer beyond memory, and carries remnants of academic CV tailoring in its public documentation.

---

## 2. Codebase Architecture & Subsystem Inspection

The system is organized into five strictly decoupled layers with downward dataflow:

```
[External JSON Source]
         │
         ▼
 1. Ingestion Layer      (ingestion/cricsheet_parser.py, ingestion/ids.py)
         │
         ▼
 2. Validation Layer     (ingestion/validator.py, ontology/shapes.yaml)
         │
         ▼
 3. Graph Storage Layer  (graph/store.py - PropertyGraph, Node, Edge)
         │
         ▼
 4. Query Engine Layer   (query/grammar.lark, parser.py, ast.py, semantic.py, planner.py, executor.py)
         │
         ▼
 5. Benchmark & Mirror   (scripts/build_sqlite_mirror.py, benchmark/*)
```

### 2.1. Ingestion Layer (`ingestion/`)
- **Components:** `ingestion/ids.py`, `ingestion/cricsheet_parser.py`.
- **Intended Responsibility:** Parse match JSON documents from cricsheet.org into normalized entity dictionaries, compute deterministic collision-resistant IDs, derive match-level aggregates (`BATTED_IN`, `BOWLED_IN`), and construct relational edges (`TEAMMATES_WITH`, `NEXT_DELIVERY`).
- **Implementation Status:** Fully functional. Correctly derives complex cricket statistics (batter boundary tallies, ICC-standard credited wickets excluding run-outs, maiden overs, and mutual teammate pairings).
- **Architectural Findings & Limitations:**
  - *ID Stability:* Uses 8-character lowercase hex IDs from cricsheet registry when present; falls back to slugged names. Slug generation is deterministic and clean.
  - *Captaincy Heuristic Defect:* Cricsheet lacks an explicit captain property. The parser designates the first-listed player per team as captain. This heuristic is historically inaccurate (e.g., producing non-captains at the top of win rankings) and acknowledged as a known limitation.
  - *Coupling:* Ingestion is hard-coded to cricsheet schemas. The graph store itself is domain-agnostic, but the ingestion layer is tightly coupled to cricket.

### 2.2. Validation Layer (`ingestion/validator.py`, `ontology/shapes.yaml`)
- **Components:** `ShapeValidator`, `ShapeViolationError`, `shapes.yaml`.
- **Intended Responsibility:** Provide declarative data integrity enforcement modeled after the W3C SHACL (Shapes Constraint Language) recommendation. Validate nodes and edges before mutation.
- **Implementation Status:** Fully functional. Validates required/optional fields, declared scalar types (`str`, `int`, `bool`), regular expression patterns (e.g., ISO date format, hex IDs), enumerated sets (match formats, wicket kinds), and numeric range boundaries (`min`/`max` balls per over).
- **Architectural Findings:**
  - Very clean design. Raises typed `ShapeViolationError` with label, field, and violation reason.
  - Rejection happens before the graph store mutates, preventing invalid or partial entities from entering memory.
  - 98% test coverage with extensive unit tests in `tests/test_validator.py`.

### 2.3. Storage Layer (`graph/store.py`)
- **Components:** `PropertyGraph`, `Node`, `Edge`.
- **Intended Responsibility:** In-memory property graph store providing idempotent entity insertion, property merging, forward and reverse adjacency lookups, and label indexing.
- **Implementation Status:** Fully functional.
  - Storage structures: `_nodes: dict[str, Node]`, `_edges: dict[str, Edge]`, `_out: dict[str, list[str]]`, `_in: dict[str, list[str]]`, `_by_label: dict[str, set[str]]`, `_edge_by_label: dict[str, set[str]]`.
  - Mutation semantics: Idempotent on ID. Re-inserting an existing node/edge merges properties (new keys override). Attempting to relabel an existing node ID raises `ValueError`.
  - Edge integrity: Enforces referential integrity; adding an edge with nonexistent `src` or `dst` raises `KeyError`.
- **Architectural Findings & Limitations:**
  - *Memory Consumption:* In-memory storage using native Python dictionaries and dataclasses scales to ~712,000 nodes and ~1.47 million edges on the full Pakistan corpus, consuming ~1.5–2.0 GB of RAM. While acceptable for workstation analysis, it does not persist across process lifecycles.
  - *No Secondary Indexing:* Indexing exists solely on primary key (`id`) and entity `label`. Filtering on node/edge properties (e.g., `city = "Karachi"`) requires iterating through all nodes of that label.

### 2.4. Query Engine Layer (`query/`)
- **Components:**
  - `grammar.lark`: EBNF specification for GQL-Core subset.
  - `parser.py`: Lark LALR/Earley parser generating frozen dataclass AST.
  - `ast.py`: Immutable AST nodes (`Query`, `Pattern`, `NodePat`, `RelPat`, `Comparison`, `And`, `Or`, `Not`, `Projection`, `OrderBy`).
  - `semantic.py`: Schema-aware semantic checker validating bindings, property existence against `shapes.yaml`, and edge endpoint compatibility.
  - `planner.py`: Logical planner emitting physical plan ops (`ScanOp`, `ExpandOp`, `JoinOp`, `FilterOp`, `ProjectOp`) with single-variable predicate pushdown.
  - `executor.py`: Stream-based plan executor supporting regular path queries (RPQ via BFS), hash joins, boolean expression evaluation, group-by aggregation (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`), and stable multi-column sorting.
- **Implementation Status:** Fully functional within its documented subset.
- **Architectural Findings & Critical Gaps:**
  - *RPQ Semantics:* Traversal uses BFS with target-node deduplication. Correctly implements Cypher reachability semantics for bounded Kleene stars (`*`, `+`, `*N`, `*M..N`).
  - *Edge Variable Limitation on Multi-hop RPQ:* Cypher binds a list of edges for variable-length patterns. This engine only tracks single edges, so specifying an edge variable on an RPQ pattern (e.g., `-[r:NEXT_DELIVERY*1..3]->`) deliberately raises `NotImplementedError` to prevent reading erroneous properties.
  - *Missing `DISTINCT`:* Syntax rejects `RETURN DISTINCT x` and `COUNT(DISTINCT x)`.
  - *Single-Clause Only:* Query must be a single `MATCH ... WHERE ... RETURN` block. No `WITH` clause piping or query composition.

### 2.5. Relational Mirror & Existing Benchmarks (`scripts/`, `benchmark/`)
- **Components:**
  - `scripts/build_sqlite_mirror.py`: Normalized relational schema generation with B-tree indexes matching every join key.
  - `benchmark/queries.py` & `logical_reasoning.py`: Hand-authored canonical query pairs (GQL-Core vs SQLite).
  - `benchmark/natural_queries.py`: 35 domain questions across 9 query classes.
  - `benchmark/vs_sqlite.py` & `run_nl_benchmark.py`: Timing and row-set verification harnesses.
  - `benchmark/nl_to_gql.py`, `query_suite.py`, `run_suite_benchmark.py`: LLM-based text-to-GQL evaluation.
- **Implementation Status:** Mixed. Core query comparison works cleanly, but the LLM and suite runners have critical runtime defects and missing files.

---

## 3. Build, Execution, and Verification Audit

### 3.1. Environment and Dependencies
- **OS:** Windows 11 (tested on PowerShell).
- **Python:** 3.14.7.
- **Package Manifest:** `pyproject.toml` pins:
  - `lark==1.2.2` (installed 1.3.1 cleanly)
  - `pyyaml==6.0.2` (installed 6.0.3 cleanly)
  - `requests==2.32.3` (installed 2.34.2 cleanly)
  - `pytest==8.3.0`, `pytest-cov==5.0.0` (installed pytest 8.4.2, pytest-cov 7.1.0 cleanly)

### 3.2. Automated Test Execution
Executing `python -m pytest --cov=. --cov-report=term-missing`:
- **Result:** **226 passed in 15.93 seconds**.
- **Total Statements:** 3,117.
- **Missed Statements:** 588.
- **Overall Code Coverage:** **81%**.

#### Subsystem Breakdown:
| Subsystem / Module | Statements | Miss | Coverage % | Status |
|---|---|---|---|---|
| `graph/store.py` | 80 | 3 | 96% | Verified production quality |
| `ingestion/ids.py` | 37 | 0 | 100% | Verified production quality |
| `ingestion/validator.py` | 93 | 2 | 98% | Verified production quality |
| `ingestion/cricsheet_parser.py` | 248 | 28 | 89% | Verified production quality |
| `query/ast.py` | 56 | 0 | 100% | Verified production quality |
| `query/parser.py` | 151 | 5 | 97% | Verified production quality |
| `query/semantic.py` | 150 | 19 | 87% | Verified production quality |
| `query/planner.py` | 116 | 13 | 89% | Verified production quality |
| `query/executor.py` | 299 | 31 | 90% | Verified production quality |
| `scripts/build_sqlite_mirror.py` | 110 | 28 | 75% | Verified production quality |
| `benchmark/vs_sqlite.py` | 160 | 47 | 71% | Verified core functionality |
| `benchmark/natural_queries.py` | 6 | 0 | 100% | Verified |
| `benchmark/logical_reasoning.py` | 6 | 0 | 100% | Verified |
| `benchmark/nl_to_gql.py` | 90 | 90 | 0% | Uncovered / Experimental |
| `benchmark/query_suite.py` | 2 | 2 | 0% | Uncovered / Experimental |
| `benchmark/run_nl_benchmark.py` | 128 | 128 | 0% | Uncovered / CLI runner |
| `benchmark/run_suite_benchmark.py` | 187 | 187 | 0% | Uncovered / Defective on Windows |

### 3.3. Manual Workflow & Script Verification Findings

#### Verification 1: Cricsheet Parser CLI
- **Command:** `python -m ingestion.cricsheet_parser tests/fixtures`
- **Output:** Ingested 5 fixture files without error; materialized 65 nodes and 112 edges.
- **Finding:** Verified working.

#### Verification 2: SQLite Mirror Generation
- **Command:** `python scripts/build_sqlite_mirror.py --data tests/fixtures --db data/test_mirror.db`
- **Output:** Built tables and indexes, matching node and edge counts exactly (16 players, 5 matches, 26 deliveries, etc.).
- **Finding:** Verified working.

#### Verification 3: Core Benchmark Runner (`vs_sqlite.py`)
- **Command:** `python -m benchmark.vs_sqlite --data tests/fixtures --iters 5 --out benchmark/results/fixture_results.json`
- **Output:** Evaluated Direct Queries (Q1–Q5) and Logical Reasoning Queries (LR1–LR5). All queries returned `result_correct: true` with 100% row parity between GQL-Core and SQLite.
- **Finding:** Verified working.

#### Verification 4: Natural-Language QA Benchmark Runner (`run_nl_benchmark.py`)
- **Command:** `python -m benchmark.run_nl_benchmark --data tests/fixtures --iters 5`
- **Result:** **CRASHED** at end of run with exit code 1.
- **Root Cause Defect:**
  ```python
  UnicodeEncodeError: 'charmap' codec can't encode character '\u2713' in position 85: character maps to <undefined>
  ```
  On Windows consoles using default code page `cp1252`, attempting to print `✓` (`\u2713`) in stdout causes a fatal exception.
- **Severity:** High (blocks out-of-the-box CLI execution on Windows).

#### Verification 5: 100-Query Suite Benchmark Runner (`run_suite_benchmark.py`)
- **Command:** `python -m benchmark.run_suite_benchmark --help`
- **Result:** **CRASHED** with exit code 1.
- **Root Cause Defect 1 (Console Encoding):**
  ```python
  UnicodeEncodeError: 'charmap' codec can't encode character '\u2192' in position 394: character maps to <undefined>
  ```
  The module docstring contains `→` (`\u2192`), which is passed to `argparse.ArgumentParser(description=__doc__)`, crashing when `--help` formats the description under `cp1252`.
- **Root Cause Defect 2 (POSIX-Only Signal):**
  Inspecting lines 34 & 73:
  ```python
  import signal
  ...
  old = signal.signal(signal.SIGALRM, _handler)
  signal.alarm(timeout)
  ```
  `signal.SIGALRM` and `signal.alarm()` do NOT exist on Windows Python (`hasattr(signal, 'SIGALRM') == False`). Invoking this runner on Windows crashes immediately.
- **Severity:** Blocker for Windows users.

#### Verification 6: Missing Result Artifact
- **Finding:** `README.md` (lines 218–220) states:
  > *"The current local Ollama run in benchmark/results/suite_benchmark.json passes 50/100 queries... See benchmark/results/suite_benchmark.json."*
- **Evidence:** `benchmark/results/suite_benchmark.json` does NOT exist in the repository tree and has never been committed in git history (`git log --all --full-history -- "benchmark/results/suite_benchmark.json"` returned empty).
- **Severity:** Technical credibility defect. Claims are asserted against an uncommitted artifact.

---

## 4. Git History & Development Direction Analysis

Reviewing the commit log:
1. `27745af` (*May 10, 2026*): "Initial implementation: 5-layer cricket knowledge graph + GQL-Core query engine"
   - Established the core five layers, shapes, parser, store, grammar, and 5 direct queries (95 tests).
2. `882e741` (*May 16, 2026*): "Add Logical Reasoning benchmark + fill executor test gaps, run on real corpus"
   - Extended corpus tests to 712K nodes; added LR1–LR5 testing RPQ transitive closure, multi-pattern joins, and co-venue paths (128 tests).
3. `f08a30a` (*May 16, 2026*): "Add Natural-Language QA Benchmark: 35 queries across 9 classes, 45/45 correct"
   - Added NQ01–NQ35, demonstrating 100% row-set parity between Cypher and SQL on domain questions (157 tests).
4. `adcc697` (*May 25, 2026*): "Add benchmark indexes and regression tests for SQL engine"
   - Added semantic validation (`query/semantic.py`), regression test suite (`tests/test_regression.py`), and experimental Ollama NL translation suite (226 tests).

**Development Direction Insight:**  
The repository developed rapidly in May 2026 with a dual focus:
- A very disciplined, well-engineered core database engine (layers 1–4) with strict regression tests, formal grammar, and oracle verification.
- An exploratory benchmark layer that progressively pushed into NL-to-GQL translation and comparative SQL expressibility.
- The project is now at a critical juncture: the core engine is solid, but the experimental translation and benchmark harness layer contains untested, platform-fragile code.

---

## 5. Benchmark Credibility Assessment: The Need for Known Standard Benchmarks

A central engineering question for this repository is: **Does the benchmark actually prove what it claims to prove?**

### Current Benchmark Strengths:
- **Exact Parity Verification:** All 45 hand-crafted benchmark queries (5 direct, 5 logical reasoning, 35 natural language) execute against both GQL-Core and SQLite, validating identical sorted row-sets (`result_correct: true`).
- **Independent Fixture Oracles:** Hand-computed answers in `tests/ground_truth.json` prevent shared ingestion bugs from creating false parity passes.
- **Expressibility Evidence:** Quantitative token counts clearly demonstrate where GQL-Core drastically simplifies queries (e.g., LR2 transitive closure: 15 GQL tokens vs 108 SQL tokens with recursive CTEs and canonical ordering logic).

### Critical Weaknesses of the Current Benchmark Strategy:
1. **Domain Isolation:** All evaluations are conducted exclusively on cricsheet cricket data. Outside observers cannot easily determine if the performance and expressibility benefits generalize to standard graph data models.
2. **Asymmetric Optimizations:** SQLite queries are compared against an in-memory Python BFS interpreter. While expressibility favors GQL, execution latency is dominated by SQLite's compiled C engine on scans and aggregations, whereas GQL only wins on specific undirected lookups and in-memory transitive closures.
3. **Absence of Recognized Standards:** The graph database community benchmarks engines using **LDBC SNB (Linked Data Benchmark Council - Social Network Benchmark)** or standard Regular Path Query (RPQ) reachability workloads. To achieve true technical credibility, the project must implement a standard benchmark adapter.

---

## 6. Audit Verdict

| Criteria | Assessment | Notes |
|---|---|---|
| **Core Architecture** | **Strong** | Clean 5-layer separation; formal grammar; shape validation. |
| **Engine Correctness** | **Strong** | 226 tests pass; robust oracle and adversarial regression suite. |
| **Code Quality** | **High** | Type annotations, immutable AST, defensive parsing. |
| **Platform Portability** | **Needs Remediation** | Crashes on Windows consoles and POSIX signals in benchmarks. |
| **Benchmark Credibility** | **Moderate** | Rigorous internal parity, but lacks recognized industry standard benchmarks. |
| **Documentation & Packaging** | **Needs Remediation** | Academic/portfolio framing; missing artifact; no entrypoints. |

The core engine is structurally sound and functionally verified. It is ready to be steered into an independent, general-purpose open-source release once platform defects are resolved, standard benchmarks are integrated, and experimental LLM scripts are properly isolated.
