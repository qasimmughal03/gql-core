# Language Compatibility Specification: openCypher & ISO GQL Subset

**Project**: GQL-Core (`gql-core`)  
**Specification Version**: `0.2.0`  
**Reference Corpus**: openCypher TCK (Release `2024.3`, commit `677cbafabb8c3c5eed458fd3b1ec0daec8d67d23`)  
**Standard Cross-Reference**: ISO/IEC 39075:2024 (Information technology — Database languages — GQL)  

---

## 1. Scope and Design Philosophy

GQL-Core v0.2.0 is an embedded, in-memory graph query library providing declarative read-only pattern matching over property graphs. It targets a clean, well-defined subset of the openCypher query language and the core pattern-matching constructs of ISO GQL.

GQL-Core **deliberately does not implement full openCypher or ISO GQL**. It prioritizes zero-dependency embedded execution, strict relational semantics, and lightweight memory consumption over language complexity (such as full mutation pipelines or complex nested subqueries).

---

## 2. Supported Language Subset

The following grammar constructs and semantics are fully supported, tested, and verified:

### 2.1 Graph Pattern Matching (`MATCH`)
- **Single-pattern clauses**: `MATCH (a:Person)-[:KNOWS]->(b:Person)`
- **Pattern topologies**:
  - Directed outgoing: `(a)-[r:TYPE]->(b)`
  - Directed incoming: `(a)<-[r:TYPE]-(b)`
  - Undirected: `(a)-[r:TYPE]-(b)`
  - Anonymous nodes and edges: `()-[]->()`
  - Multi-hop fixed-length patterns: `(a)-[:KNOWS]->(b)-[:WORKS_AT]->(c)`
- **Inline property patterns**: `(n:Person {id: 42, name: 'Alice'})`
- **Relationship trail semantics (Relationship Isomorphism)**:
  - Within a single pattern part, no relationship instance may be traversed more than once.
  - Nodes may be revisited (allowing self-loops and cycles across distinct edges).

### 2.2 Regular Path Queries (RPQs)
- **Quantifiers supported**:
  - One or more: `-[:NEXT+]->`
  - Zero or more (Kleene star): `-[:NEXT*]->`
  - Bounded ranges: `-[:NEXT*1..3]->`
  - Exact hops: `-[:NEXT*2..2]->`
- **Traversal semantics**:
  - Breadth-first frontier expansion.
  - Cycle-safe: tracks visited node states along path frontiers to guarantee termination on cyclic graphs.

### 2.3 Predicates & Filtering (`WHERE`)
- **Comparison operators**: `=`, `!=`, `<`, `<=`, `>`, `>=`
- **Logical operators**: `AND`, `OR`, `NOT`, and parenthesized sub-expressions
- **Literals**: Integers, floats, strings (single and double quoted), booleans (`true`, `false`), and `null`
- **Missing property semantics**: Missing properties evaluate to `null`; comparisons against missing properties safely evaluate according to standard three-valued / null logic without raising runtime crashes.

### 2.4 Projections (`RETURN`)
- **Explicit aliasing**: `RETURN n.name AS playerName, r.runs AS total`
- **Binding projections**: `RETURN n` (returns the full node dictionary with id, label, props)
- **Aggregation functions**:
  - `COUNT(*)`: Total matched rows
  - `COUNT(var)` / `COUNT(var.prop)`: Non-null count
  - `SUM(var.prop)`: Numeric summation
  - `AVG(var.prop)`: Arithmetic mean
  - `MIN(var.prop)`: Minimum value
  - `MAX(var.prop)`: Maximum value
- **Implicit Grouping**: When aggregate functions and scalar expressions are combined, rows are grouped by all non-aggregate projections.

### 2.5 Result Ordering & Pagination
- **Multi-column sorting**: `ORDER BY p.score DESC, p.id ASC`
- **Pagination**: `LIMIT <n>`

---

## 3. Declared Unsupported Features

Queries containing any of the following features are outside GQL-Core v0.2.0's language subset and are either rejected at parse time with a `LarkError` or static `SemanticError`, or classified as `unsupported` in conformance harnesses:

| Language Feature | openCypher / GQL Construct | Rationale / Status |
| :--- | :--- | :--- |
| **Mutations** | `CREATE`, `MERGE`, `DELETE`, `DETACH`, `SET`, `REMOVE` | GQL-Core v0.2.0 is strictly a read-only query engine. Graph building is performed via Python graph APIs (`add_node`, `add_edge`, `from_networkx`). |
| **Intermediate Pipeline Clauses** | `WITH`, `UNWIND`, `CALL`, `UNION` | Multi-clause piping requires an intermediate tabular pipeline execution engine, deferred to future milestones. |
| **Multiple MATCH Clauses** | `MATCH ... MATCH ...` | Independent pattern cross-joins without WITH are not supported. |
| **Conditionals** | `CASE WHEN ... THEN ... ELSE ... END` | Deferred to future scalar expression release. |
| **Shortest Path Built-ins** | `shortestPath()`, `allShortestPaths()` | RPQ quantifiers (`*lo..hi`) cover bounded path queries; weighted algorithms are external. |
| **Built-in Scalar Functions** | `coalesce()`, `size()`, `length()`, `type()`, `id()`, `labels()`, `head()`, `tail()`, `collect()` | Scalar functions are not implemented in the v0.2.0 parser grammar. |
| **Multi-Label Predicates** | `(:Post|Comment)` | GQL-Core nodes have a single concrete primary label. |
| **Standalone RETURN** | `RETURN 1 + 1` | In GQL-Core, every query must contain at least one `MATCH` pattern. |

---

## 4. openCypher TCK Compatibility Evaluation

### 4.1 Test Methodology
- **Corpus**: Official [openCypher TCK](https://github.com/opencypher/openCypher) pinned to release `2024.3` (commit `677cbafabb8c3c5eed458fd3b1ec0daec8d67d23`).
- **Adapter**: Strict Gherkin scenario parser and executor (`benchmark/tck/`).
- **Verification Rules**:
  - Exact column matching (no positional fallback).
  - Strict type checking (integers must not match booleans or strings).
  - Error category matching: syntax/compile errors must raise `(LarkError, SemanticError)`; arbitrary runtime crashes register as failures.
  - Multi-set row matching: verifies exact row counts and values (order-sensitive when `in order` is specified).

### 4.2 Comprehensive TCK Coverage Results

```
============================================================
  openCypher TCK Compatibility Suite (pinned to 2024.3)
============================================================
  Total Scenarios Inventoried:       1338
  Classified as Unsupported:          1259 (94.10%)
  In Claimed Language Subset:         79
  Passed within Claimed Subset:       76 / 79 (96.20%)
  Failed within Claimed Subset:       3 / 79  (3.80%)
  Blocked Scenarios:                  0
  Overall openCypher Suite Coverage:  5.68% (76/1338)
============================================================
```

#### Breakdown by Scenario Category
- **`clauses`**: 753 total | 58 passed | 694 unsupported | 1 failed
- **`expressions`**: 555 total | 8 passed | 545 unsupported | 2 failed
- **`useCases`**: 30 total | 10 passed | 20 unsupported | 0 failed

#### Primary Unsupported Feature Drivers (Denominator: 1,259)
1. `STANDALONE_RETURN_WITHOUT_MATCH`: 567 scenarios (45.0%)
2. `MULTIPLE_MATCH_CLAUSES`: 164 scenarios (13.0%)
3. `WITH_CLAUSE`: 99 scenarios (7.9%)
4. `PATH_VARIABLE_ASSIGNMENT`: 64 scenarios (5.1%)
5. `MUTATION_SET`: 55 scenarios (4.4%)
6. `MUTATION_DELETE`: 39 scenarios (3.1%)
7. `MUTATION_REMOVE`: 32 scenarios (2.5%)
8. `MUTATION_CREATE`: 22 scenarios (1.7%)
9. `MUTATION_MERGE`: 20 scenarios (1.6%)
10. Other functions & syntax: 197 scenarios (15.6%)

### 4.3 Detailed Inventory of the 3 Non-Passing Scenarios

All 3 non-passing scenarios stem from openCypher's requirement that **unaliased expressions must preserve verbatim source text as column keys**:

1. **`Return4#4`** (`clauses/return/Return4.feature`):
   - Query: `MATCH (n) RETURN cOuNt( * )`
   - Expected column header: `"cOuNt( * )"`
   - GQL-Core column header: `"count"`
   - Root cause: GQL-Core normalizes unaliased aggregate projections to lowercase canonical names (`count`).

2. **`Aggregation1#1`** (`expressions/aggregation/Aggregation1.feature`):
   - Query: `MATCH (n) RETURN n.name, count(n.num)`
   - Expected column headers: `"n.name"`, `"count(n.num)"`
   - GQL-Core column headers: `"name"`, `"count_n_num"`
   - Root cause: GQL-Core uses clean attribute keys (`prop` or `agg_var_prop`) rather than qualified expression strings.

3. **`Aggregation3#1`** (`expressions/aggregation/Aggregation3.feature`):
   - Query: `MATCH (n) RETURN n.name, sum(n.num)`
   - Expected column headers: `"n.name"`, `"sum(n.num)"`
   - GQL-Core column headers: `"name"`, `"sum_n_num"`
   - Root cause: Identical attribute key naming convention as `Aggregation1#1`.

*Note: In all three scenarios, supplying standard SQL/Cypher explicit aliases (e.g. `RETURN n.name AS name, count(n.num) AS cnt`) results in 100% exact conformity.*

---

## 5. Relationship to ISO GQL (ISO/IEC 39075:2024)

ISO GQL standardizes property graph querying across commercial and open-source database engines. GQL-Core aligns with ISO GQL in the following architectural respects:
1. **Property Graph Data Model**: Labeled nodes and directed edges with key-value property bags.
2. **Path Pattern Syntax**: Bounded quantifiers (`{lo,hi}` and `*lo..hi`) and arrow notation (`->`, `<-`, `-`).
3. **Relational Result Format**: Queries project structured tabular bindings compatible with relational data models.

*Disclaimer*: Partial openCypher compatibility or ISO GQL syntactic alignment does not constitute official certification of conformance to either standard.
