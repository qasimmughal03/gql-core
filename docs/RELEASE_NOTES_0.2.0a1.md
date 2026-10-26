# GQL-Core Release Notes — Version 0.2.0a1

**Release Target**: `0.2.0a1` (Public Alpha Release)  
**Release Date**: October 27, 2026  
**License**: Apache-2.0  
**Supported Python Versions**: Python 3.11, 3.12, 3.13  
**Repository**: [`qasimmughal03/knowledge-graoh-with-formal-query`](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query)  
**Git Release Commit**: `5a96672`

---

## 1. What is GQL-Core?

GQL-Core is an in-memory, embedded property-graph database and reasoning engine written in pure Python. It combines:
1. **A textual graph query interface** executing openCypher and ISO/IEC 39075:2024 (GQL) pattern matching, filtering, mutations, and aggregations.
2. **A programmatic, typed logical query API (`PlanBuilder`)** for compile-time validated graph and relational algebra.
3. **A stratified Datalog ontology inference engine** computing deterministic deductive closures over graph facts.
4. **An independent, hardened verification harness** enforcing exact openCypher TCK compliance and LDBC SNB correctness.

GQL-Core operates in-process with zero external server dependencies, making it suitable for analytical workloads, embedded graph algorithms, testing, and autonomous AI agents.

---

## 2. Key Implemented Capabilities

### 2.1 Textual Query Frontend (`gql_core.run`)
- **Clauses**: `MATCH`, `OPTIONAL MATCH`, `WHERE`, `WITH`, `RETURN`, `UNWIND`, `CREATE`, `MERGE`, `SET`, `DELETE`, `DETACH DELETE`, `REMOVE`, `UNION`, `UNION ALL`, `CALL`.
- **Graph Traversal**: Single and multi-hop paths (`[*min..max]`), relationship trail uniqueness (relationship isomorphism), directed and undirected matching, and path variable assignment.
- **Three-Valued Logic (3VL)**: Strict Kleene null semantics for boolean operators (`AND`, `OR`, `NOT`, `XOR`) and comparison predicates.
- **Mutations & Referential Integrity**: Node and relationship creation with property maps; cascading relationship deletion on `DETACH DELETE`; primary and secondary label index synchronization on `REMOVE`.
- **Ordering & Aggregation**: Arbitrary expression evaluation in `ORDER BY [ASC|DESC]`; discrete and continuous percentile aggregations (`percentileDisc`, `percentileCont`); standard aggregations (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `COLLECT`, `stDev`, `stDevP`).
- **openCypher Temporal Engine**: Native ISO-8601 parsing, component extraction, duration arithmetic, and truncation for `Date`, `Time`, `LocalTime`, `DateTime`, `LocalDateTime`, and `Duration`.
- **Quantifiers & Comprehensions**: List and pattern comprehensions `[x IN c WHERE pred | expr]`; 3VL quantifiers `all()`, `any()`, `single()`, `none()`.

### 2.2 Programmatic Typed Query Plan API (`PlanBuilder`)
- Immutable intermediate representation (IR) supporting `Scan`, `Expand`, `Filter`, `Project`, `Sort`, `Limit`, `Skip`, `Join`, and `Union`.
- Pre-execution plan validation via `validate_logical_plan()` with detailed error reporting.
- Deterministic plan execution via `execute_plan()`.

### 2.3 Ontology & Datalog Inference Subsystem
- Semi-naive forward chaining fixed-point evaluation.
- Built-in rule factories: transitive closure, inverse relationships, symmetric relationships, relational composition, and subtype inheritance.
- Full provenance tracking recording which rule generated each derived fact.
- Graph materialization to write derived facts back to the in-memory `PropertyGraph`.

### 2.4 Zero-Friction Adapters
- Ingestion from NetworkX graphs (`from_networkx`) preserving node types and multigraph parallel edges.
- Record list ingestion (`from_records`) preserving integer `0` IDs and falsy values.
- Edge tuple ingestion (`from_edges`) and dictionary ingestion (`from_dict`).

---

## 3. How to Install and Use

### Installation
From the repository:

```bash
git clone https://github.com/qasimmughal03/knowledge-graoh-with-formal-query.git
cd knowledge-graoh-with-formal-query
python -m pip install -e .
```

To install optional developer and benchmark dependencies:

```bash
python -m pip install -e ".[dev,benchmark]"
```

### Quick Example

```python
import gql_core
from gql_core import PropertyGraph, Node, Edge

graph = PropertyGraph()
graph.add_node(Node("alice", "Person", {"name": "Alice"}))
graph.add_node(Node("bob", "Person", {"name": "Bob"}))
graph.add_edge(Edge("e1", "KNOWS", "alice", "bob"))

results = gql_core.run(
    "MATCH (a:Person)-[:KNOWS]->(b:Person) WHERE a.name = 'Alice' RETURN b.name AS friend",
    graph,
)
print(results)  # [{'friend': 'Bob'}]
```

For detailed guides, consult:
- [`docs/QUICKSTART.md`](QUICKSTART.md)
- [`docs/API_REFERENCE.md`](API_REFERENCE.md)
- [`examples/`](../examples/)

---

## 4. Experimental Alpha Status & Compatibility Boundaries

GQL-Core `0.2.0a1` is an **experimental public alpha**.
- It is not a production database server.
- The storage engine is entirely in-memory and does not provide ACID durability, disk persistence, or multi-user transaction isolation.
- Concurrent reads under standard CPython GIL are thread-safe; concurrent mutations require application-level locking.
- It is not certified under ISO/IEC 39075:2024 (GQL) or certified by Neo4j / openCypher.

---

## 5. Known Limitations & Excluded Features

The following 18 openCypher TCK scenarios are explicitly unsupported in `0.2.0a1`:
1. **Grammar null-filter shortcuts (`Null2#5..7`)**: Syntax using `IS NOT NULL` directly within inline pattern filters.
2. **Conjunctive label creation syntax (`Create2#13..14`, `Create3#1`)**: Multiple colon conjunctions in `CREATE` patterns.
3. **Nested comprehension undirected projections (`Match1#11..12`)**: Undirected pattern projection inside nested list comprehensions.
4. **Hexadecimal & octal integer literals (`Literal1#1..2`)**: `0x...` and `0o...` literal parsing.
5. **Dynamic bracket map subscripting (`Map2#1..2`)**: Dynamic map lookup via arbitrary runtime expressions.
6. **Server catalog introspection (`UseCases#1..2`)**: Schema metadata introspection queries requiring catalog support.
7. **Unicode escape normalization (`String1#1..3`)**: Non-standard Unicode normalization sequences.

---

## 6. Verified Benchmark & Verification Results

All reported results are derived from reproducible machine-readable artifacts:

| Suite | Metric | Result |
| :--- | :--- | :--- |
| **Strict openCypher TCK (Full Corpus)** | Pinned 2024.3 release (3,897 scenarios) | **3,879 / 3,879 supported passed (100.00%)** |
| — Result Checks | Exact row and column matching | **3,187 / 3,187 (100.00%)** |
| — Expected Error Checks | Category & phase validation | **692 / 692 (100.00%)** |
| — Mutation Side Effects | Exact graph state delta assertions | **250 / 250 checked (3,187 total SE passed)** |
| — Defect Count | Failed result / compile / runtime / blocked | **0** |
| **Strict openCypher TCK (Non-Outline)** | 1,339 scenarios | **1,321 / 1,321 supported passed (100.00%)** |
| **Unit & Regression Tests** | `pytest tests/` | **341 / 341 passed (100.00%)** in 25.8s |
| **LDBC SNB Interactive SF0.1** | 327k nodes, 1.47M edges | **4 / 4 official (7 / 7 total) exact matches** against SQLite Oracle |

*Disclaimer: The LDBC study is an unaudited read-only performance study using LDBC SNB Interactive v1 queries.*

---

## 7. Reporting Issues & Community

Please report bugs, questions, or unexpected query outputs on GitHub:
👉 **[GitHub Issues](https://github.com/qasimmughal03/knowledge-graoh-with-formal-query/issues)**

When filing an issue, please include:
1. Python version and platform OS.
2. Minimal graph initialization snippet.
3. Exact query or `PlanBuilder` call.
4. Expected vs. actual output.
