# GQL-Core Logical Operator & IR Specification

**Version**: 1.0  
**Status**: Implemented & Verified  
**Package**: `gql_core.ir`  

---

## 1. Overview

GQL-Core provides a canonical, strongly typed, immutable logical Intermediate Representation (IR) for expressing graph, relational, Boolean, quantified, temporal, and ontology queries. The IR is decoupled from concrete query syntax, enabling both programmatic execution (via [`PlanBuilder`](gql_core/builder.py)) and automated generation by LLM agents.

All expressions and operators conform to strict typing, deterministic evaluation, and safe versioned JSON serialization (zero `eval` or dynamic code execution).

---

## 2. Value Expressions

All value expressions inherit from [`ValueExpr`](gql_core/ir.py).

| Expression | Arguments | Output Type | Description |
| :--- | :--- | :--- | :--- |
| `Literal(value, data_type)` | `value: Any`, `data_type: DataType` | Specified | Literal constant (`int`, `float`, `str`, `bool`, `Date`, etc.). |
| `Variable(name, data_type)` | `name: str` | Specified | Reference to a bound variable in the current row context. |
| `Property(var, prop, data_type)` | `var: str`, `prop: str` | Specified | Attribute access on an entity or map (`var.prop`). Returns `None` if missing. |
| `Parameter(name, data_type)` | `name: str` | Specified | External query parameter binding. |
| `Arithmetic(op, lhs, rhs)` | `op: '+'|'-'|'*'|'/'|'%'`, `lhs, rhs: ValueExpr` | Numeric / Temporal | Numeric and temporal arithmetic. Zero-division safely evaluates to `None`. |
| `FunctionCall(name, args)` | `name: str`, `args: tuple[ValueExpr, ...]` | Dynamic | Scalar functions: `COALESCE`, `SIZE`, `ABS`, `UPPER`, `LOWER`, `TO_INT`, `TO_FLOAT`, `TO_STRING`, `TO_BOOL`, `TO_DATE`, `TO_DATETIME`. |
| `ListExpr(elements)` | `elements: tuple[ValueExpr, ...]` | `LIST` | Construct an ordered collection. |
| `MapExpr(entries)` | `entries: tuple[tuple[str, ValueExpr], ...]` | `MAP` | Construct a key-value mapping. |
| `TemporalExpr(type_name, args)`| `type_name: str`, `args: tuple` | Temporal | Instantiates typed `Date`, `Time`, `DateTime`, `Duration`, or `Interval`. |
| `AggregateExpr(func, expr, distinct)` | `func: 'COUNT'|'SUM'|'AVG'|'MIN'|'MAX'|'COLLECT'`, `expr: ValueExpr | None`, `distinct: bool` | Numeric / List | Aggregation expression evaluated over partitioned groups. |
| `CaseExpr(cases, else_expr)` | `cases: tuple[tuple[BoolExpr, ValueExpr], ...]`, `else_expr: ValueExpr | None` | Result type | Conditional branch (`CASE WHEN ... THEN ... ELSE ...`). |
| `CoalesceExpr(expressions)` | `expressions: tuple[ValueExpr, ...]` | First non-null | Returns the first non-null evaluated argument. |

---

## 3. Boolean Predicates & Three-Valued Logic (3VL)

All Boolean expressions inherit from [`BoolExpr`](gql_core/ir.py) and evaluate under Kleene 3-Valued Logic:
- **`True`**
- **`False`**
- **`None`** (Unknown)

In `Filter` operations, rows are retained strictly if the predicate evaluates to `True`. Rows evaluating to `False` or `None` are discarded.

### 3.1 Kleene Truth Tables

| P | Q | `NOT P` | `P AND Q` | `P OR Q` |
| :---: | :---: | :---: | :---: | :---: |
| `True` | `True` | `False` | `True` | `True` |
| `True` | `False` | `False` | `False` | `True` |
| `True` | `None` | `False` | `None` | `True` |
| `False` | `True` | `True` | `False` | `True` |
| `False` | `False` | `True` | `False` | `False` |
| `False` | `None` | `True` | `False` | `None` |
| `None` | `True` | `None` | `None` | `True` |
| `None` | `False` | `None` | `False` | `None` |
| `None` | `None` | `None` | `None` | `None` |

### 3.2 Boolean Operators

- **`And(children)`**: Conjunction with Kleene short-circuit evaluation.
- **`Or(children)`**: Disjunction with Kleene short-circuit evaluation.
- **`Not(inner)`**: Negation (`NOT Unknown -> Unknown`).
- **`Comparison(op, lhs, rhs)`**: Operators `=`, `!=`, `<`, `<=`, `>`, `>=`. Comparison against `None` returns `None`. Strict mismatch between boolean and non-boolean evaluates to `False` (`=`) or `True` (`!=`).
- **`IsNull(expr)` / `IsNotNull(expr)`**: Null check.
- **`IsMissing(var, prop)` / `IsPresent(var, prop)`**: Explicit property existence check.
- **`In(element, collection)` / `NotIn(element, collection)`**: Collection membership.
- **`Between(expr, low, high)` / `NotBetween(expr, low, high)`**: Range inclusion test (`low <= expr <= high`).
- **`StringMatch(op, string_expr, pattern_expr)`**: Operators `STARTS_WITH`, `ENDS_WITH`, `CONTAINS`.
- **`RegexMatch(string_expr, pattern)`**: Regular expression pattern matching.

---

## 4. Graph & Correlated Existence Predicates

- **`PatternExpr(source_var, rel_label, direction, target_var, target_label, min_hops, max_hops, target_filter)`**: Defines a graph pattern template bound to an outer variable.
- **`Exists(subquery_or_pattern)`**: Returns `True` if at least one matching path or subquery row exists. Terminates immediately upon first match.
- **`NotExists(subquery_or_pattern)`**: Negated existence probe.

---

## 5. Quantified Relationship Reasoning

- **`QuantifiedRel(quantifier, source_var, rel_label, direction, target_var, target_label, predicate, count, count_mode)`**:
  - `quantifier`: `ANY`, `ALL`, `NONE`, `SINGLE`, `AT_LEAST`, `AT_MOST`, `EXACTLY`, `COUNT_SATISFYING`.
  - `count_mode`: `entities` (distinct nodes), `relationships` (edge instances), `paths`, `rows`.
  - **Vacuous Truth**: For `ALL`, if 0 related entities exist, the predicate evaluates to `True`.

---

## 6. Relational & Graph Operators

All relational operators inherit from [`RelOp`](gql_core/ir.py) and emit tabular rows:

1. **`Scan(var, label, inline_filters)`**: Root scan over graph entities.
2. **`Expand(input, from_var, edge_var, edge_label, direction, to_var, to_label, optional)`**: 1-hop relationship traversal. Supports `optional=True` for left outer graph joins.
3. **`RecursiveExpand(input, from_var, edge_var, edge_label, direction, min_hops, max_hops, to_var, to_label, trail_semantics)`**: Regular path query with openCypher trail semantics (no repeated edges).
4. **`Filter(input, predicate)`**: Predicate filtering under 3VL logic.
5. **`Project(input, projections, distinct)`**: Expression projection and optional distinct deduplication.
6. **`Join(left, right, on, kind)`**: Relational join. `kind` supports `INNER`, `LEFT_OUTER`, `SEMI`, `ANTI`, `CROSS`.
7. **`Union(left, right, all)`**: Set union (`all=False`) or multiset bag union (`all=True`).
8. **`Intersect(left, right, all)`**: Set intersection (`all=False`) or multiset intersection (`all=True`).
9. **`Except(left, right, all)`**: Set difference (`all=False`) or multiset difference (`all=True`).
10. **`GroupBy(input, keys, aggregates)`**: Hash-based grouping and multi-aggregate evaluation.
11. **`Having(input, predicate)`**: Post-aggregation predicate filtering.
12. **`Sort(input, terms)`**: Multi-key sort with deterministic null ordering.
13. **`Limit(input, count, offset)`**: Window pagination with early termination.

---

## 7. Versioned JSON Serialization

Every plan serializes to a clean, safe JSON representation:

```json
{
  "version": "1.0",
  "_type": "Project",
  "input": {
    "version": "1.0",
    "_type": "Filter",
    "input": {
      "version": "1.0",
      "_type": "Scan",
      "var": "p",
      "label": "Person",
      "inline_filters": []
    },
    "predicate": {
      "_type": "Comparison",
      "op": ">",
      "lhs": {"_type": "Property", "var": "p", "prop": "age", "data_type": "ANY"},
      "rhs": {"_type": "Literal", "value": 30, "data_type": "ANY"}
    }
  },
  "projections": [
    {"expr": {"_type": "Property", "var": "p", "prop": "name", "data_type": "ANY"}, "alias": "name"}
  ],
  "distinct": false
}
```
Deserialization uses [`plan_from_dict`](gql_core/ir.py) and executes zero dynamic code.
