# GQL-Core Supported Query Contract

**Version**: `0.2.0a1` (Experimental Release)  
**Standard Compliance**: ISO/IEC 39075:2024 (GQL) Core Subset & openCypher Compatible Grammar  
**Measured Coverage**: 1,321 / 1,339 openCypher TCK Scenarios (98.66% Corpus Coverage, 100.00% Supported-Subset Accuracy)

---

## 1. Scope & Design Philosophy

GQL-Core provides a dual-interface architecture:
1. **Textual Frontend (`gql_core.run`)**: An openCypher and ISO GQL compatible textual query parser, semantic validator, and pipeline executor.
2. **Typed Logical API (`PlanBuilder`, `execute_plan`)**: A programmatic, type-safe intermediate representation (IR) supporting relational algebra, Kleene 3-valued logic, quantified graph reasoning, correlated subqueries, and deterministic Datalog ontology inference.

### Core Release Contract Rule
> **Zero Silent Failures**: Any operation within the declared supported contract MUST execute and return verified, exact answers (`1,176 / 1,176 PASS_RESULT` and `145 / 145 PASS_EXPECTED_ERROR`). Any feature outside the declared supported contract MUST fail explicitly at compile time (`SyntaxError`, `SemanticError`, `LarkError`) or runtime (`NotImplementedError`), and NEVER return misleading, unverified, or silently wrong results.

---

## 2. Textual Query Frontend Contract (`gql_core.run`)

### 2.1 Supported Clauses

| Clause | Status | Capabilities & Constraints |
|---|---|---|
| `MATCH` | **SUPPORTED** | Directed single and multi-hop patterns `(a)-[:REL]->(b)`, undirected patterns `(a)-[:REL]-(b)`, multi-label node patterns `(a:Label1:Label2)`, variable-length paths `[*min..max]`, inline property filters with literal or dynamic expressions `(:Label {prop: val})`, and path variable binding `p = (a)-[*]->(b)`. |
| `OPTIONAL MATCH` | **SUPPORTED** | Left-outer graph pattern joins with standard `null` padding across unbound node, relationship, and path variables. |
| `WHERE` | **SUPPORTED** | Full 3-valued Kleene Boolean logic (`AND`, `OR`, `NOT`, `XOR`), chained and parenthesized comparisons (`=`, `<>`, `<`, `<=`, `>`, `>=`), `IS NULL`, `IS NOT NULL`, conjunctive label predicates (`n:A:B`), string predicates (`STARTS WITH`, `ENDS WITH`, `CONTAINS`, `=~` regex), pattern predicates, and `IN` collection membership. |
| `WITH` | **SUPPORTED** | Multi-clause projection, mandatory aliasing (`AS`) for expressions/aggregations, `DISTINCT`, grouping, filtering (`WHERE`), ordering (`ORDER BY`), `SKIP`, and `LIMIT`. |
| `RETURN` | **SUPPORTED** | Aliasing (`AS`), `DISTINCT`, whole-row projections (`*`), aggregations (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `COLLECT`, `percentileDisc`, `percentileCont`, `stDev`, `stDevP`), `ORDER BY [ASC|DESC]`, `SKIP`, and `LIMIT`. |
| `UNWIND` | **SUPPORTED** | List and collection flattening into row streams (`UNWIND [1, 2, 3] AS x`). |
| `CREATE` | **SUPPORTED** | Node (single and multi-label) and relationship creation with property maps, path bindings, and variable binding. |
| `MERGE` | **SUPPORTED** | Idempotent graph pattern matching/creation with `ON CREATE SET` and `ON MATCH SET` actions. |
| `SET` | **SUPPORTED** | Property assignments (`SET n.prop = val`), map replacement (`SET n = {..}`), map merge (`SET n += {..}`), and label additions (`SET n:NewLabel`). |
| `DELETE` / `DETACH DELETE` | **SUPPORTED** | Node, relationship, and path deletion, with cascading incident edge deletion under `DETACH` and strict compile-time rejection of invalid targets. |
| `REMOVE` | **SUPPORTED** | Property removal (`REMOVE n.prop`) and multi-label removal (`REMOVE n:Label1:Label2`). |
| `UNION` / `UNION ALL` | **SUPPORTED** | Set union with full intra- and inter-branch deduplication (`UNION`) and multiset concatenation (`UNION ALL`). |
| `CALL` | **SUPPORTED** | Standalone and in-query procedure invocations with argument type checking and `YIELD` bindings. |

### 2.2 Supported Expressions, Functions & Comprehensions

- **List & Pattern Comprehensions**: `[x IN list WHERE pred | expr]`, `[(a)-[r]->(b) WHERE pred | expr]`, and quantifier predicates `all(x IN list WHERE pred)`, `any(...)`, `none(...)`, `single(...)`.
- **Type Conversions**: `toInteger(x)`, `toFloat(x)`, `toString(x)`, `toBoolean(x)` (returning `null` safely on unparseable strings).
- **Mathematical**: `abs(x)`, `round(x)`, `ceil(x)`, `floor(x)`, `sqrt(x)`, `sign(x)`, `rand()`, `e()`, `pi()`, `exp(x)`, `log(x)`, `log10(x)`, `sin(x)`, `cos(x)`, `tan(x)`, `asin(x)`, `acos(x)`, `atan(x)`, `atan2(y, x)`, `cot(x)`, `degrees(x)`, `radians(x)`, `haversin(x)`.
- **String Functions**: `toLower(s)`, `toUpper(s)`, `trim(s)`, `ltrim(s)`, `rtrim(s)`, `reverse(s)`, `size(s)`, `split(s, delim)`, `substring(s, start, len)`, `replace(s, search, rep)`.
- **Graph & Collection Functions**: `size(c)`, `length(path)`, `head(c)`, `last(c)`, `tail(c)`, `range(start, end, step)`, `keys(entity)`, `labels(node)`, `type(rel)`, `id(entity)`, `startNode(rel)`, `endNode(rel)`, `properties(entity)`, `nodes(path)`, `relationships(path)`, `coalesce(...)`.
- **Temporal Functions & Arithmetic**:
  - Constructors: `date(...)`, `time(...)`, `localtie(...)`, `datetime(...)`, `localdatetime(...)`, `datetime.fromEpoch(...)`, `datetime.fromEpochMillis(...)`, `duration(...)`, `duration.between(...)`, `duration.inMonths(...)`, `duration.inDays(...)`, `duration.inSeconds(...)`.
  - Component accessors: `.year`, `.quarter`, `.month`, `.week`, `.weekYear`, `.day`, `.ordinalDay`, `.weekDay`, `.dayOfQuarter`, `.hour`, `.minute`, `.second`, `.millisecond`, `.microsecond`, `.nanosecond`, `.timezone`, `.offset`, `.offsetMinutes`, `.offsetSeconds`, `.epochSeconds`, `.epochMillis`, and duration components.

### 2.3 Explicitly Excluded Features in `0.2.0a1` (18 TCK Scenarios)

The following two openCypher syntax extensions are explicitly outside the `0.2.0a1` textual query contract and are classified as `UNSUPPORTED`:
1. **`CORRELATED_SUBQUERY_EXISTS` (10 TCK scenarios)**: Full nested `EXISTS { MATCH ... WHERE ... }` subqueries and multi-hop pattern comprehensions with correlated inner `WHERE` clauses inside textual Cypher expressions (`MatchWhere2#5-#8`, `ExistentialSubquery1#1-#3`, `PatternComprehension1#4, #8`, `TriadicSelection1#1`). *Note: Correlated `EXISTS` is supported programmatically via `PlanBuilder`.*
2. **`MULTI_REL_TYPE_DISJUNCTION` (8 TCK scenarios)**: Pipe-separated relationship type disjunctions `[:TYPE_A|TYPE_B]` in textual `MATCH` patterns (`Match2#7, #8, #12`, `Match4#6, #7`, `Match6#9`, `Match7#10`, `TriadicSelection1#2`).

---

## 3. Typed Logical Plan Interface Contract (`PlanBuilder`)

The programmatic IR supports relational and graph algebra operations:

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
- **Supported Axioms**: Subtype hierarchies (`make_subtype_rule`), Symmetric relationships (`make_symmetric_rule`), Inverse relationships (`make_inverse_rule`), Transitive relationships (`make_transitive_rule`), and Relational composition (`make_composition_rule`).
- **Reasoning Modes**: Closed-World Assumption (CWA) and Open-World Assumption (OWA) with explicit `OntologyViolationError` on schema constraint violations.
- **Provenance Tracking**: Every derived edge retains metadata tracing the generating inference rule and premise edges.
