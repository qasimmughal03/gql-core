# GQL-Core Typed Query API & Builder Guide

**Version**: 1.0  
**Status**: Stable Public API  
**Package**: `gql_core.builder`, `gql_core.registry`  

---

## 1. Overview

GQL-Core provides a fluent, type-safe Python API for constructing and executing query plans programmatically. Users and LLM agents can assemble complex relational, graph, Boolean, and aggregate queries without writing raw textual Cypher strings.

---

## 2. PlanBuilder Fluent Interface

The [`PlanBuilder`](file:///c:/Users/HP/Documents/Portfolio/knowledge-graoh-with-formal-query/gql_core/builder.py) class offers chainable methods:

```python
from gql_core import (
    PlanBuilder,
    PropertyGraph,
    and_,
    at_least_rel,
    avg,
    col,
    count,
    eq,
    execute_plan,
    exists,
    gt,
    lit,
    pattern,
    prop,
    sum_,
    var,
)

# 1. Initialize graph
graph = PropertyGraph()
# ... populate graph ...

# 2. Build typed query plan
plan = (
    PlanBuilder.scan("u", "User", status="active")
    .expand("PURCHASES", to_var="p", to_label="Product", from_var="u")
    .filter(gt(prop("p", "price"), lit(25.0)))
    .project(
        (prop("u", "name"), "user_name"),
        (prop("p", "price"), "price"),
    )
    .sort((col("price"), "DESC"))
    .limit(10)
    .build()
)

# 3. Execute plan deterministically
result = execute_plan(plan, graph)
for row in result["rows"]:
    print(row["user_name"], row["price"])
```

---

## 3. Helper Expression Constructors

Convenience factory functions for value and boolean expressions:

| Constructor | Signature | Returns | Description |
| :--- | :--- | :--- | :--- |
| `var(name)` / `col(name)` | `name: str` | `Variable` | References variable `name`. |
| `prop(var, prop)` | `var: str, prop: str` | `Property` | Accesses attribute `var.prop`. |
| `lit(val)` | `val: Any` | `Literal` | Creates literal value. |
| `eq(l, r)` / `neq(l, r)` | `l, r: ValueExpr` | `Comparison` | Equality / inequality. |
| `lt(l, r)` / `lte(l, r)` / `gt(l, r)` / `gte(l, r)` | `l, r: ValueExpr` | `Comparison` | Ordered comparisons. |
| `and_(*children)` | `*children: BoolExpr` | `And` | Conjunction (3VL). |
| `or_(*children)` | `*children: BoolExpr` | `Or` | Disjunction (3VL). |
| `not_(inner)` | `inner: BoolExpr` | `Not` | Negation (3VL). |
| `is_null(expr)` / `is_not_null(expr)` | `expr: ValueExpr` | `IsNull` / `IsNotNull` | Null check. |
| `is_missing(var, prop)` / `is_present(var, prop)` | `var, prop: str` | `IsMissing` / `IsPresent` | Property presence check. |
| `in_(elem, coll)` / `not_in(elem, coll)` | `elem, coll: ValueExpr` | `In` / `NotIn` | Collection membership. |
| `between(expr, low, high)` | `expr, low, high: ValueExpr` | `Between` | Range check. |
| `pattern(src, rel, dst, ...)` | `src, rel, dst, ...` | `PatternExpr` | Graph pattern template. |
| `exists(pat_or_sub)` / `not_exists(pat_or_sub)` | `PatternExpr | RelOp` | `Exists` / `NotExists` | Correlated existence. |
| `all_rel(...)` / `any_rel(...)` / `none_rel(...)` / `single_rel(...)` / `at_least_rel(n, ...)` | `...` | `QuantifiedRel` | Relationship quantification. |
| `count(expr, distinct)` / `sum_(expr)` / `avg(expr)` / `min_(expr)` / `max_(expr)` / `collect(expr)` | `...` | `AggregateExpr` | Aggregation functions. |
| `case_when(cases, else_expr)` | `...` | `CaseExpr` | Conditional branching. |
| `coalesce(*expressions)` | `...` | `CoalesceExpr` | First non-null value. |

---

## 4. Logical Plan Validation

Plans are validated before execution using [`validate_logical_plan`](file:///c:/Users/HP/Documents/Portfolio/knowledge-graoh-with-formal-query/gql_core/validator_ir.py):

```python
from gql_core import PlanValidationError, validate_logical_plan

try:
    report = validate_logical_plan(plan, strict=True)
except PlanValidationError as e:
    print(f"Validation failed: {e.code} at {e.path}: {e.message}")
```

### Validation Error Codes:
- `UNBOUND_VARIABLE`: Reference to an undeclared variable.
- `JOIN_KEY_MISSING`: Join key absent from left or right relation.
- `SET_OP_SCHEMA_MISMATCH`: Set algebra operands have incompatible projected columns.
- `INVALID_BOUNDS`: Negative limits or inverted hop bounds (`min_hops > max_hops`).
- `INVALID_OPERATOR`: Unrecognized operator class in plan tree.

---

## 5. Safe Serialization & LLM Integration

Plans serialize cleanly to JSON and deserialize without `eval`:

```python
# To JSON
json_text = plan.to_json(indent=2)

# From JSON
recovered_builder = PlanBuilder.from_json(json_text)
```

### 5.1 LLM Operator Prompt Generation
[`OperatorRegistry.generate_llm_prompt(schema)`](file:///c:/Users/HP/Documents/Portfolio/knowledge-graoh-with-formal-query/gql_core/registry.py) generates a markdown prompt describing all available entity types, properties, relationships, and operators, allowing an LLM to generate valid structured plans.
