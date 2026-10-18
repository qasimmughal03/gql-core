# GQL-Core Supported Query Contract

**Version**: `0.2.0a1` (Experimental Release)  
**Standard Compliance**: ISO/IEC 39075:2024 (GQL) Core Subset & openCypher Compatible Grammar  

---

## 1. Scope & Design Philosophy

GQL-Core provides a dual-interface architecture:
1. **Textual Frontend (`gql_core.run`)**: An openCypher and ISO GQL compatible textual query parser and executor.
2. **Typed Logical API (`PlanBuilder`, `execute_plan`)**: A programmatic, type-safe intermediate representation (IR) supporting relational algebra, Kleene 3-valued logic, quantified graph reasoning, and deterministic Datalog ontology inference.

### Core Release Contract Rule
> **Zero Silent Failures**: Any operation within the declared supported contract MUST execute and return verified, correct answers. Any feature outside the declared supported contract MUST reject explicitly at compile time (`SyntaxError`, `SemanticError`, `LarkError`) or runtime (`NotImplementedError`), and NEVER return misleading, unverified, or silently wrong results.

---

## 2. Textual Query Frontend Contract (`gql_core.run`)

### 2.1 Supported Clauses

| Clause | Status | Capabilities & Constraints |
|---|---|---|
| `MATCH` | **SUPPORTED** | Directed single and multi-hop patterns `(a)-[:REL]->(b)`, undirected patterns `(a)-[:REL]-(b)`, inline property filters `(:Label {prop: val})`, and path variable binding `p = (a)->(b)`. |
| `OPTIONAL MATCH` | **SUPPORTED** | Left-outer graph joins with standard `null` padding across unbound node, relationship, and path variables. |
| `WHERE` | **SUPPORTED** | Full 3-valued Kleene Boolean logic (`AND`, `OR`, `NOT`, `XOR`), comparisons (`=`, `<>`, `<`, `<=`, `>`, `>=`), `IS NULL`, `IS NOT NULL`, string predicates (`STARTS WITH`, `ENDS WITH`, `CONTAINS`, `=~` regex), and `IN` collection membership. |
| `WITH` | **SUPPORTED** | Multi-clause projection, aliasing, grouping, filtering (`WHERE`), ordering (`ORDER BY`), `SKIP`, and `LIMIT`. |
| `RETURN` | **SUPPORTED** | Aliasing (`AS`), `DISTINCT`, whole-row projections (`*`), aggregations (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `COLLECT`), `ORDER BY [ASC|DESC]`, `SKIP`, and `LIMIT`. |
| `UNWIND` | **SUPPORTED** | List and collection flattening into row streams (`UNWIND [1, 2, 3] AS x`). |
| `CREATE` | **SUPPORTED** | Node and relationship creation with property maps and variable binding. |
| `MERGE` | **SUPPORTED** | Idempotent graph pattern matching with `ON CREATE SET` and `ON MATCH SET` actions. |
| `SET` | **SUPPORTED** | Property assignments (`SET n.prop = val`) and label additions (`SET n:NewLabel`). |
| `DELETE` / `DETACH DELETE` | **SUPPORTED** | Node and relationship deletion, with cascading edge deletion under `DETACH`. |
| `REMOVE` | **SUPPORTED** | Property removal (`REMOVE n.prop`) and label removal (`REMOVE n:OldLabel`). |
| `UNION` / `UNION ALL` | **SUPPORTED** | Set union with strict deduplication (`UNION`) and multiset concatenation (`UNION ALL`). |
| `CALL` | **SUPPORTED** | In-query and standalone procedure invocations with argument type checking and `YIELD` bindings. |

### 2.2 Supported Scalar Functions & Operators

- **Type Conversions**: `toInteger(x)`, `toFloat(x)`, `toString(x)`, `toBoolean(x)` (return `null` safely on unparseable string input).
- **Mathematical**: `abs(x)`, `round(x)`, `ceil(x)`, `floor(x)`, `sqrt(x)`, `sign(x)`, `rand()`.
- **String Functions**: `toLower(s)`, `toUpper(s)`, `trim(s)`, `ltrim(s)`, `rtrim(s)`, `reverse(s)`, `length(s)`.
- **List & Collection Functions**: `size(c)`, `head(c)`, `tail(c)`, `range(start, end, step)`, `keys(map)`, `labels(node)`, `nodes(path)`.
- **Temporal Functions**:
  - Constructors: `date(...)`, `time(...)`, `datetime(...)`, `duration(...)`.
  - Component accessors: `.year`, `.quarter`, `.month`, `.week`, `.day`, `.hour`, `.minute`, `.second`, `.millisecond`, `.microsecond`, `.nanosecond`, `.timezone`, `.offset`, `.offsetMinutes`, `.offsetSeconds`, `.months`, `.days`.
- **Dynamic Access**: Bracket operator for list indexing (`list[0]`) and dynamic map property access (`map['key']`, `map[toString(idx)]`).

### 2.3 Explicitly Unsupported Cypher Syntax (Rejected at Compile Time)

1. Multiple relationship type alternatives in patterns (`MATCH (a)-[:TYPE_A|TYPE_B]->(b)`).
2. Cypher shortest path builtins (`shortestPath(...)`, `allShortestPaths(...)`).
3. Subquery expressions inside expressions (`CALL { ... }`).
4. Map projection shorthand (`n { .id, .name }`).

---

## 3. Typed Logical Plan Interface Contract (`PlanBuilder`)

The programmatic IR supports operations exceeding the textual frontend:

| Logical Operator | IR Construct | Capabilities |
|---|---|---|
| `Scan` | `PlanBuilder.scan(var, label, **filters)` | Indexed label scan with inline pushed property predicates. |
| `Expand` | `.expand(label, to_var, from_var, direction)` | 1-hop relational expansion with directionality and edge binding. |
| `RecursiveExpand` | `.recursive_expand(label, min_hops, max_hops)` | Transitive closure and BFS Regular Path Query (RPQ) traversal. |
| `QuantifiedRel` | `quantified_rel(quantifier, ...)` | Quantified graph patterns: `ALL`, `ANY`, `NONE`, `SINGLE`, `AT_LEAST(k)`, `AT_MOST(k)`, `EXACTLY(k)`. |
| `Correlated EXISTS` | `exists(subquery)` / `not_exists(subquery)` | Correlated existence checking over complex path patterns. |
| `Relational Algebra` | `.join()`, `.left_join()`, `.semi_join()`, `.anti_join()` | Relational equi-joins, semi-joins, and anti-joins over binding streams. |
| `Set Algebra` | `.union()`, `.intersect()`, `.except_()` | Full set operations with duplicate and distinct semantics. |
| `Hash GroupBy` | `.group_by(keys, *aggs)` | Multi-key hash aggregation supporting `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `COLLECT`. |

---

## 4. Ontology Inference Contract (`InferenceEngine`)

The ontology engine implements deterministic bottom-up Datalog inference over the graph:
- **Supported Axioms**:
  - Subtype hierarchies (`make_subtype_rule`)
  - Symmetric relationships (`make_symmetric_rule`)
  - Inverse relationships (`make_inverse_rule`)
  - Transitive relationships (`make_transitive_rule`)
  - Relational composition (`make_composition_rule`)
- **Reasoning Modes**:
  - Closed-World Assumption (CWA): Asserted facts are exhaustive; missing edges are false.
  - Open-World Assumption (OWA): Missing information is unknown; schema cardinality violations trigger explicit `OntologyViolationError`.
- **Provenance Tracking**: Every derived edge retains metadata tracing the generating inference rule and premise edges.
