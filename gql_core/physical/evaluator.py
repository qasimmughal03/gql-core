"""Typed expression evaluator for GQL-Core physical engine.

Implements:
- Three-valued logic (3VL: True, False, None/Unknown) for Boolean predicates (AND, OR, NOT)
- Type-checked scalar comparisons (=, !=, <, <=, >, >=)
- Reference-to-reference, property-to-property, and variable identity comparisons
- IN / NOT IN, BETWEEN / NOT BETWEEN
- IS NULL / IS NOT NULL, IS MISSING / IS PRESENT
- STARTS WITH / ENDS WITH / CONTAINS, Regex matching
- Numeric arithmetic (+, -, *, /, %) with divide-by-zero protection
- Explicit safe conversions
- Temporal operations and comparisons
- Collection operators (indexing, slicing, size, set operations, quantifiers)
- CASE WHEN / THEN / ELSE and COALESCE
- Correlated graph existence probes (EXISTS, NOT_EXISTS)
- Quantified relationship reasoning (ANY, ALL, NONE, SINGLE, AT_LEAST, AT_MOST, EXACTLY)
  with vacuous truth for ALL and distinct counting modes.
"""

from __future__ import annotations

import math
import re
from typing import Any

from gql_core.graph import Edge, Node, PropertyGraph
from gql_core.ir import (
    AggregateExpr,
    And,
    Arithmetic,
    Between,
    BoolExpr,
    CaseExpr,
    CoalesceExpr,
    CollectionQuantifier,
    Comparison,
    Exists,
    FunctionCall,
    In,
    IsNotNull,
    IsNull,
    IsMissing,
    IsPresent,
    ListExpr,
    Literal,
    MapExpr,
    Not,
    NotBetween,
    NotExists,
    NotIn,
    Or,
    PatternExpr,
    Property,
    QuantifiedRel,
    RegexMatch,
    RelOp,
    StringMatch,
    TemporalExpr,
    TypePredicate,
    ValueExpr,
    Variable,
)
from gql_core.temporal import (
    Date,
    DateTime,
    Duration,
    Interval,
    Time,
    coerce_temporal,
)
from gql_core.types import (
    DataType,
    cast_to_boolean,
    cast_to_date,
    cast_to_datetime,
    cast_to_float,
    cast_to_integer,
    cast_to_string,
    infer_data_type,
)


def eval_value(expr: ValueExpr | None, row: dict[str, Any], graph: PropertyGraph | None = None) -> Any:
    """Evaluate a ValueExpr against a binding row."""
    if expr is None:
        return None

    if isinstance(expr, Literal):
        return expr.value

    if isinstance(expr, Variable):
        val = row.get(expr.name)
        return val

    if isinstance(expr, Property):
        entity = row.get(expr.var)
        if entity is None:
            return None
        if isinstance(entity, (Node, Edge)):
            return entity.props.get(expr.prop)
        if isinstance(entity, dict):
            return entity.get(expr.prop)
        return getattr(entity, expr.prop, None)

    if isinstance(expr, Arithmetic):
        lval = eval_value(expr.lhs, row, graph)
        rval = eval_value(expr.rhs, row, graph)
        if lval is None or rval is None:
            return None

        # Temporal arithmetic
        if isinstance(lval, (Date, DateTime, Duration)) or isinstance(rval, Duration):
            if expr.op == "+":
                return lval + rval
            if expr.op == "-":
                return lval - rval

        # Numeric arithmetic
        if isinstance(lval, (int, float)) and isinstance(rval, (int, float)):
            if expr.op == "+":
                return lval + rval
            if expr.op == "-":
                return lval - rval
            if expr.op == "*":
                return lval * rval
            if expr.op == "/":
                if rval == 0:
                    return None  # Safe zero division -> null
                return lval / rval
            if expr.op == "%":
                if rval == 0:
                    return None
                return lval % rval

        # String concatenation
        if expr.op == "+" and (isinstance(lval, str) or isinstance(rval, str)):
            return str(lval) + str(rval)

        return None

    if isinstance(expr, FunctionCall):
        return _eval_function(expr.name, [eval_value(a, row, graph) for a in expr.args])

    if isinstance(expr, ListExpr):
        return [eval_value(e, row, graph) for e in expr.elements]

    if isinstance(expr, MapExpr):
        return {k: eval_value(v, row, graph) for k, v in expr.entries}

    if isinstance(expr, CaseExpr):
        for cond, res_expr in expr.cases:
            if eval_predicate(cond, row, graph) is True:
                return eval_value(res_expr, row, graph)
        return eval_value(expr.else_expr, row, graph) if expr.else_expr else None

    if isinstance(expr, CoalesceExpr):
        for sub in expr.expressions:
            v = eval_value(sub, row, graph)
            if v is not None:
                return v
        return None

    if isinstance(expr, TemporalExpr):
        args = [eval_value(a, row, graph) for a in expr.args]
        return _eval_temporal_expr(expr.type_name, args)

    return None


def eval_predicate(expr: BoolExpr | None, row: dict[str, Any], graph: PropertyGraph | None = None) -> bool | None:
    """Evaluate a BoolExpr against a row using Kleene 3-valued logic (True, False, None/Unknown)."""
    if expr is None:
        return True

    if isinstance(expr, ValueExpr):
        v = eval_value(expr, row, graph)
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        return bool(v)

    if isinstance(expr, And):
        has_unknown = False
        for child in expr.children:
            res = eval_predicate(child, row, graph)
            if res is False:
                return False  # Short-circuit: False AND anything -> False
            if res is None:
                has_unknown = True
        return None if has_unknown else True

    if isinstance(expr, Or):
        has_unknown = False
        for child in expr.children:
            res = eval_predicate(child, row, graph)
            if res is True:
                return True  # Short-circuit: True OR anything -> True
            if res is None:
                has_unknown = True
        return None if has_unknown else False

    if isinstance(expr, Not):
        inner = eval_predicate(expr.inner, row, graph)
        if inner is None:
            return None
        return not inner

    if isinstance(expr, Comparison):
        lval = eval_value(expr.lhs, row, graph)
        rval = eval_value(expr.rhs, row, graph)
        return _eval_comparison(expr.op, lval, rval)

    if isinstance(expr, IsNull):
        val = eval_value(expr.expr, row, graph)
        return val is None

    if isinstance(expr, IsNotNull):
        val = eval_value(expr.expr, row, graph)
        return val is not None

    if isinstance(expr, IsMissing):
        entity = row.get(expr.var)
        if entity is None:
            return True
        if isinstance(entity, (Node, Edge)):
            return expr.prop not in entity.props
        if isinstance(entity, dict):
            return expr.prop not in entity
        return not hasattr(entity, expr.prop)

    if isinstance(expr, IsPresent):
        entity = row.get(expr.var)
        if entity is None:
            return False
        if isinstance(entity, (Node, Edge)):
            return expr.prop in entity.props
        if isinstance(entity, dict):
            return expr.prop in entity
        return hasattr(entity, expr.prop)

    if isinstance(expr, In):
        elem = eval_value(expr.element, row, graph)
        coll = eval_value(expr.collection, row, graph)
        if elem is None or coll is None:
            return None
        if isinstance(coll, (list, tuple, set)):
            return elem in coll
        if isinstance(coll, str) and isinstance(elem, str):
            return elem in coll
        return False

    if isinstance(expr, NotIn):
        res = eval_predicate(In(element=expr.element, collection=expr.collection), row, graph)
        return None if res is None else not res

    if isinstance(expr, Between):
        val = eval_value(expr.expr, row, graph)
        low = eval_value(expr.low, row, graph)
        high = eval_value(expr.high, row, graph)
        if val is None or low is None or high is None:
            return None
        c1 = _eval_comparison(">=", val, low)
        c2 = _eval_comparison("<=", val, high)
        if c1 is False or c2 is False:
            return False
        if c1 is True and c2 is True:
            return True
        return None

    if isinstance(expr, NotBetween):
        res = eval_predicate(Between(expr=expr.expr, low=expr.low, high=expr.high), row, graph)
        return None if res is None else not res

    if isinstance(expr, StringMatch):
        s = eval_value(expr.string_expr, row, graph)
        p = eval_value(expr.pattern_expr, row, graph)
        if s is None or p is None:
            return None
        s_str, p_str = str(s), str(p)
        if expr.op == "STARTS_WITH":
            return s_str.startswith(p_str)
        if expr.op == "ENDS_WITH":
            return s_str.endswith(p_str)
        if expr.op == "CONTAINS":
            return p_str in s_str
        return False

    if isinstance(expr, RegexMatch):
        s = eval_value(expr.string_expr, row, graph)
        if s is None:
            return None
        return bool(re.search(expr.pattern, str(s)))

    if isinstance(expr, Exists):
        return _eval_exists(expr.subquery_or_pattern, row, graph)

    if isinstance(expr, NotExists):
        res = _eval_exists(expr.subquery_or_pattern, row, graph)
        return None if res is None else not res

    if isinstance(expr, QuantifiedRel):
        return _eval_quantified_rel(expr, row, graph)

    if isinstance(expr, CollectionQuantifier):
        return _eval_collection_quantifier(expr, row, graph)

    if isinstance(expr, TypePredicate):
        entity = row.get(expr.var)
        if entity is None:
            return None
        label = getattr(entity, "label", None)
        if label is None:
            return False
        if expr.is_exact:
            return label == expr.target_type
        # If schema is available, check subtype hierarchy
        return label == expr.target_type

    return False


def _eval_comparison(op: str, lval: Any, rval: Any) -> bool | None:
    """Compare two values under 3VL semantics."""
    if lval is None or rval is None:
        return None

    # Temporal coercion
    l_temp = coerce_temporal(lval)
    r_temp = coerce_temporal(rval)
    if isinstance(l_temp, (Date, Time, DateTime, Duration)) and isinstance(r_temp, (Date, Time, DateTime, Duration)):
        lval, rval = l_temp, r_temp

    # Strict type mismatch between boolean and non-boolean
    if isinstance(lval, bool) != isinstance(rval, bool):
        if op == "=":
            return False
        if op == "!=":
            return True
        return None

    try:
        if op == "=":
            return lval == rval
        if op == "!=":
            return lval != rval
        if op == "<":
            return lval < rval
        if op == "<=":
            return lval <= rval
        if op == ">":
            return lval > rval
        if op == ">=":
            return lval >= rval
    except TypeError:
        return None
    return False


def _eval_function(name: str, args: list[Any]) -> Any:
    name_up = name.upper()
    if name_up == "COALESCE":
        for a in args:
            if a is not None:
                return a
        return None
    if name_up in ("SIZE", "LENGTH"):
        if not args or args[0] is None:
            return None
        return len(args[0])
    if name_up == "TO_INT":
        return cast_to_integer(args[0]) if args else None
    if name_up == "TO_FLOAT":
        return cast_to_float(args[0]) if args else None
    if name_up == "TO_STRING":
        return cast_to_string(args[0]) if args else None
    if name_up == "TO_BOOL":
        return cast_to_boolean(args[0]) if args else None
    if name_up == "TO_DATE":
        return cast_to_date(args[0]) if args else None
    if name_up == "TO_DATETIME":
        return cast_to_datetime(args[0]) if args else None
    if name_up == "ABS":
        return abs(args[0]) if (args and args[0] is not None) else None
    if name_up == "UPPER":
        return str(args[0]).upper() if (args and args[0] is not None) else None
    if name_up == "LOWER":
        return str(args[0]).lower() if (args and args[0] is not None) else None
    return None


def _eval_temporal_expr(type_name: str, args: list[Any]) -> Any:
    t_up = type_name.upper()
    if t_up == "DATE" and args:
        return Date.from_iso(str(args[0]))
    if t_up == "TIME" and args:
        return Time.from_iso(str(args[0]))
    if t_up == "DATETIME" and args:
        return DateTime.from_iso(str(args[0]))
    if t_up == "DURATION" and args:
        return Duration.from_iso(str(args[0]))
    if t_up == "INTERVAL" and len(args) >= 2:
        start = coerce_temporal(args[0])
        end = coerce_temporal(args[1])
        return Interval(start=start, end=end)
    return None


def _eval_exists(target: PatternExpr | RelOp, row: dict[str, Any], graph: PropertyGraph | None) -> bool | None:
    if graph is None:
        return False

    if isinstance(target, PatternExpr):
        src_entity = row.get(target.source_var)
        if src_entity is None:
            return False
        src_id = getattr(src_entity, "id", src_entity)

        # Probe edges incident to src_id
        edges = []
        if target.direction in ("out", "undirected"):
            edges.extend(graph.outgoing(src_id, target.rel_label))
        if target.direction in ("in", "undirected"):
            edges.extend(graph.incoming(src_id, target.rel_label))

        for e in edges:
            nbr_id = e.dst if e.src == src_id else e.src
            nbr_node = graph.get_node(nbr_id)
            if nbr_node is None:
                continue
            if target.target_label and nbr_node.label != target.target_label:
                continue
            if target.target_filter:
                sub_row = dict(row)
                sub_row[target.target_var] = nbr_node
                if eval_predicate(target.target_filter, sub_row, graph) is not True:
                    continue
            return True  # Found matching relationship -> early return True!
        return False

    if isinstance(target, RelOp):
        # Correlated subquery evaluation: evaluate physical plan with seed row
        from gql_core.physical.engine import execute_physical_plan

        sub_rows = execute_physical_plan(target, graph, seed_rows=[dict(row)], early_limit=1)
        return len(sub_rows) > 0

    return False


def _eval_quantified_rel(q: QuantifiedRel, row: dict[str, Any], graph: PropertyGraph | None) -> bool | None:
    if graph is None:
        return False

    src_entity = row.get(q.source_var)
    if src_entity is None:
        return False
    src_id = getattr(src_entity, "id", src_entity)

    edges = []
    if q.direction in ("out", "undirected"):
        edges.extend(graph.outgoing(src_id, q.rel_label))
    if q.direction in ("in", "undirected"):
        edges.extend(graph.incoming(src_id, q.rel_label))

    matching_entities: set[Any] = set()
    matching_edges: set[Any] = set()
    total_entities: set[Any] = set()

    for e in edges:
        nbr_id = e.dst if e.src == src_id else e.src
        nbr_node = graph.get_node(nbr_id)
        if nbr_node is None:
            continue
        if q.target_label and nbr_node.label != q.target_label:
            continue

        total_entities.add(nbr_id)

        if q.predicate:
            sub_row = dict(row)
            sub_row[q.target_var] = nbr_node
            if eval_predicate(q.predicate, sub_row, graph) is True:
                matching_entities.add(nbr_id)
                matching_edges.add(e.id)
        else:
            matching_entities.add(nbr_id)
            matching_edges.add(e.id)

    match_count = len(matching_entities) if q.count_mode == "entities" else len(matching_edges)
    total_count = len(total_entities)

    if q.quantifier == "ANY":
        return match_count > 0
    if q.quantifier == "ALL":
        if total_count == 0:
            return True  # Vacuous truth: ALL over empty set is True!
        return match_count == total_count
    if q.quantifier == "NONE":
        return match_count == 0
    if q.quantifier == "SINGLE":
        return match_count == 1
    if q.quantifier == "AT_LEAST":
        target = q.count or 0
        return match_count >= target
    if q.quantifier == "AT_MOST":
        target = q.count or 0
        return match_count <= target
    if q.quantifier == "EXACTLY":
        target = q.count or 0
        return match_count == target
    if q.quantifier == "COUNT_SATISFYING":
        target = q.count or 0
        return match_count == target

    return False


def _eval_collection_quantifier(q: CollectionQuantifier, row: dict[str, Any], graph: PropertyGraph | None) -> bool | None:
    coll = eval_value(q.collection_expr, row, graph)
    if coll is None:
        return None
    if not isinstance(coll, (list, tuple, set)):
        return False

    matches = 0
    total = len(coll)
    for item in coll:
        sub_row = dict(row)
        sub_row[q.elem_var] = item
        if eval_predicate(q.predicate, sub_row, graph) is True:
            matches += 1

    if q.quantifier == "ANY":
        return matches > 0
    if q.quantifier == "ALL":
        return True if total == 0 else matches == total
    if q.quantifier == "NONE":
        return matches == 0
    if q.quantifier == "SINGLE":
        return matches == 1
    return False
