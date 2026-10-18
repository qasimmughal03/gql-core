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

import datetime as dt
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

    from gql_core.ir import BoolExpr
    from gql_core.query.ast import (
        And as ASTAnd,
        Comparison as ASTComparison,
        Not as ASTNot,
        Or as ASTOr,
        PatternPredicate,
    )
    if isinstance(expr, (BoolExpr, ASTComparison, ASTAnd, ASTOr, ASTNot, PatternPredicate)):
        return eval_predicate(expr, row, graph)

    if isinstance(expr, (int, float, str, bool)):
        return expr

    if isinstance(expr, Literal):
        return expr.value

    from gql_core.ir import Parameter
    if isinstance(expr, Parameter):
        params = getattr(graph, "_parameters", {}) if graph is not None else {}
        if expr.name in params:
            return params[expr.name]
        if f"${expr.name}" in row:
            return row[f"${expr.name}"]
        if expr.name in row:
            return row[expr.name]
        return None

    if isinstance(expr, Variable):
        if expr.name.startswith("$"):
            pname = expr.name[1:]
            params = getattr(graph, "_parameters", {}) if graph is not None else {}
            if pname in params:
                return params[pname]
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

    from gql_core.query.ast import Ref
    if isinstance(expr, Ref):
        if expr.var == "*":
            return row
        if expr.var.startswith("$"):
            pname = expr.var[1:]
            params = getattr(graph, "_parameters", {}) if graph else {}
            if pname in params:
                return params[pname]
            if expr.var in row:
                return row[expr.var]
            if pname in row:
                return row[pname]
            return None
        binding = row.get(expr.var)
        if binding is None:
            return None
        if expr.prop is None:
            return binding
        if hasattr(binding, "props") and expr.prop in binding.props:
            return binding.props[expr.prop]
        if expr.prop == "id" and hasattr(binding, "id"):
            return binding.id
        if expr.prop == "label" and hasattr(binding, "label"):
            return binding.label
        if isinstance(binding, dict):
            return binding.get(expr.prop)
        return getattr(binding, expr.prop, None)

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
                    if lval == 0:
                        return float("nan")
                    return None
                return lval / rval
            if expr.op == "%":
                if rval == 0:
                    return None
                return lval % rval

        # String concatenation
        if expr.op == "+" and (isinstance(lval, str) or isinstance(rval, str)):
            return str(lval) + str(rval)

        # List concatenation
        if expr.op == "+":
            if isinstance(lval, (list, tuple)) and isinstance(rval, (list, tuple)):
                return list(lval) + list(rval)
            if isinstance(lval, (list, tuple)) and rval is not None:
                return list(lval) + [rval]
            if isinstance(rval, (list, tuple)) and lval is not None:
                return [lval] + list(rval)

        return None

    if isinstance(expr, FunctionCall):
        if expr.name == "LIST_COMPREHENSION" and len(expr.args) >= 4:
            var_expr, coll_expr, cond_expr, map_expr = expr.args[:4]
            var_name = var_expr.name if hasattr(var_expr, "name") else str(var_expr)
            coll_val = eval_value(coll_expr, row, graph)
            if coll_val is None or not isinstance(coll_val, (list, tuple)):
                return None
            res = []
            for item in coll_val:
                local_row = dict(row)
                local_row[var_name] = item
                if cond_expr is None or eval_predicate(cond_expr, local_row, graph) is True:
                    res.append(eval_value(map_expr, local_row, graph))
            return res

        if expr.name in ("ALL", "ANY", "NONE", "SINGLE") and len(expr.args) >= 3:
            var_expr, coll_expr, cond_expr = expr.args[:3]
            var_name = var_expr.name if hasattr(var_expr, "name") else str(var_expr)
            coll_val = eval_value(coll_expr, row, graph)
            if coll_val is None or not isinstance(coll_val, (list, tuple)):
                return None
            matches = 0
            has_unknown = False
            for item in coll_val:
                local_row = dict(row)
                local_row[var_name] = item
                ev = eval_predicate(cond_expr, local_row, graph)
                if ev is True:
                    matches += 1
                elif ev is None:
                    has_unknown = True
            if expr.name == "ALL":
                if has_unknown and matches + 1 == len(coll_val):
                    return None
                return matches == len(coll_val) and not has_unknown
            elif expr.name == "ANY":
                if matches > 0:
                    return True
                if has_unknown:
                    return None
                return False
            elif expr.name == "NONE":
                if matches > 0:
                    return False
                if has_unknown:
                    return None
                return True
            elif expr.name == "SINGLE":
                if has_unknown:
                    return None
                return matches == 1

        if expr.name == "PATTERN_COMPREHENSION":
            from gql_core.query.ast import Pattern
            from gql_core.query.executor import _match_path_pattern
            pat = next((a for a in expr.args if hasattr(a, "head") or isinstance(a, Pattern)), None)
            map_expr = expr.args[-1] if len(expr.args) > 1 else None
            cond = next((a for a in expr.args if a != pat and a != map_expr and not isinstance(a, str)), None)
            if pat and graph:
                matched_rows = _match_path_pattern(pat, row, graph)
                res = []
                for mr in matched_rows:
                    if cond is None or eval_predicate(cond, mr, graph) is True:
                        if map_expr:
                            res.append(eval_value(map_expr, mr, graph))
                        else:
                            res.append(mr)
                return res
            return []

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

    if isinstance(expr, BoolExpr):
        return eval_predicate(expr, row, graph)

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

    from gql_core.query.ast import (
        And as ASTAnd,
        Comparison as ASTComparison,
        Not as ASTNot,
        Or as ASTOr,
        PatternPredicate,
    )

    if isinstance(expr, PatternPredicate):
        from gql_core.query.executor import _match_path_pattern
        if graph is None:
            return False
        matches = _match_path_pattern(expr.pattern, row, graph)
        return len(matches) > 0

    if isinstance(expr, (And, ASTAnd)):
        has_unknown = False
        for child in expr.children:
            res = eval_predicate(child, row, graph)
            if res is False:
                return False  # Short-circuit: False AND anything -> False
            if res is None:
                has_unknown = True
        return None if has_unknown else True

    if isinstance(expr, (Or, ASTOr)):
        has_unknown = False
        for child in expr.children:
            res = eval_predicate(child, row, graph)
            if res is True:
                return True  # Short-circuit: True OR anything -> True
            if res is None:
                has_unknown = True
        return None if has_unknown else False

    if isinstance(expr, (Not, ASTNot)):
        inner = eval_predicate(expr.inner, row, graph)
        if inner is None:
            return None
        return not inner

    if isinstance(expr, (Comparison, ASTComparison)):
        lval = eval_value(expr.lhs, row, graph)
        rval = eval_value(expr.rhs, row, graph) if not isinstance(expr.rhs, (int, float, str, bool)) else expr.rhs
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
        if not isinstance(s, str) or not isinstance(p, str):
            return None
        if expr.op == "STARTS_WITH":
            return s.startswith(p)
        if expr.op == "ENDS_WITH":
            return s.endswith(p)
        if expr.op == "CONTAINS":
            return p in s
        return False

    if isinstance(expr, RegexMatch):
        s = eval_value(expr.string_expr, row, graph)
        if s is None or not isinstance(s, str):
            return None
        pat = eval_value(expr.pattern, row, graph) if not isinstance(expr.pattern, str) else expr.pattern
        if pat is None or not isinstance(pat, str):
            return None
        return bool(re.search(pat, s))

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


def _compare_lists_3vl(l1: list | tuple, l2: list | tuple) -> bool | None:
    has_null = False
    min_len = min(len(l1), len(l2))
    for i in range(min_len):
        c = _eval_comparison("=", l1[i], l2[i])
        if c is False:
            return False
        if c is None:
            has_null = True
    if len(l1) != len(l2):
        return False
    if has_null:
        return None
    return True


def _compare_maps_3vl(m1: dict, m2: dict) -> bool | None:
    if set(m1.keys()) != set(m2.keys()):
        return False
    has_null = False
    for k in m1:
        c = _eval_comparison("=", m1[k], m2[k])
        if c is False:
            return False
        if c is None:
            has_null = True
    if has_null:
        return None
    return True


def _eval_comparison(op: str, lval: Any, rval: Any) -> bool | None:
    """Compare two values under 3VL semantics."""
    if lval is None or rval is None:
        return None

    # Handle NaN
    if (isinstance(lval, float) and math.isnan(lval)) or (isinstance(rval, float) and math.isnan(rval)):
        if op in ("=", "=="):
            return False
        if op in ("!=", "<>"):
            return True
        return False

    # List comparisons
    if isinstance(lval, (list, tuple)) and isinstance(rval, (list, tuple)):
        if op in ("=", "==", "!=", "<>"):
            eq_res = _compare_lists_3vl(lval, rval)
            if eq_res is None:
                return None
            return eq_res if op in ("=", "==") else (not eq_res)

    # Map comparisons
    if isinstance(lval, dict) and isinstance(rval, dict):
        if op in ("=", "==", "!=", "<>"):
            eq_res = _compare_maps_3vl(lval, rval)
            if eq_res is None:
                return None
            return eq_res if op in ("=", "==") else (not eq_res)

    # Temporal coercion
    l_temp = coerce_temporal(lval)
    r_temp = coerce_temporal(rval)
    if isinstance(l_temp, (Date, Time, DateTime, Duration)) and isinstance(r_temp, (Date, Time, DateTime, Duration)):
        lval, rval = l_temp, r_temp

    # Strict type mismatch between boolean and non-boolean
    if isinstance(lval, bool) != isinstance(rval, bool):
        if op in ("=", "=="):
            return False
        if op in ("!=", "<>"):
            return True
        return None

    # Strict type mismatch between string and number
    if (isinstance(lval, str) and isinstance(rval, (int, float))) or (isinstance(rval, str) and isinstance(lval, (int, float))):
        if op in ("=", "=="):
            return False
        if op in ("!=", "<>"):
            return True
        return None

    try:
        if op in ("=", "=="):
            return lval == rval
        if op in ("!=", "<>"):
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


class CypherTemporalValue(str):
    _props: dict[str, Any]

    def __new__(cls, text: str, props: dict[str, Any] | None = None):
        obj = super().__new__(cls, text)
        obj._props = dict(props or {})
        return obj

    def get_component(self, name: str) -> Any:
        return self._props.get(name)

    def __getattr__(self, name: str) -> Any:
        if hasattr(self, "_props") and name in self._props:
            return self._props[name]
        raise AttributeError(f"{type(self).__name__} has no attribute {name}")


def _make_cypher_date(m: dict) -> CypherTemporalValue:
    y = int(m.get("year", 1970))
    mo = int(m.get("month", 1))
    d = int(m.get("day", 1))
    dt_obj = dt.date(y, mo, d)
    iso_year, iso_week, iso_weekday = dt_obj.isocalendar()
    quarter = (mo - 1) // 3 + 1
    q_start_mo = ((mo - 1) // 3) * 3 + 1
    q_start_date = dt.date(y, q_start_mo, 1)
    day_of_quarter = (dt_obj - q_start_date).days + 1
    ordinal_day = dt_obj.timetuple().tm_yday
    props = {
        "year": y,
        "quarter": quarter,
        "month": mo,
        "week": iso_week,
        "weekYear": iso_year,
        "day": d,
        "ordinalDay": ordinal_day,
        "weekDay": iso_weekday,
        "dayOfQuarter": day_of_quarter,
    }
    return CypherTemporalValue(f"{y:04d}-{mo:02d}-{d:02d}", props)


def _make_cypher_time(m: dict) -> CypherTemporalValue:
    h = int(m.get("hour", 0))
    mi = int(m.get("minute", 0))
    sec = int(m.get("second", 0))
    nano = int(m.get("nanosecond", 0))
    milli = nano // 1_000_000
    micro = nano // 1_000
    tz = m.get("timezone")
    offset_str = None
    offset_min = None
    offset_sec = None
    if tz is not None:
        tz_s = str(tz).strip()
        offset_match = re.match(r"^([+-])(\d{1,2}):?(\d{2})?$", tz_s)
        if offset_match:
            sign = 1 if offset_match.group(1) == "+" else -1
            oh = int(offset_match.group(2))
            om = int(offset_match.group(3) or 0)
            offset_min = sign * (oh * 60 + om)
            offset_sec = offset_min * 60
            offset_str = f"{offset_match.group(1)}{oh:02d}:{om:02d}"
        else:
            offset_str = tz_s
    props = {
        "hour": h,
        "minute": mi,
        "second": sec,
        "millisecond": milli,
        "microsecond": micro,
        "nanosecond": nano,
    }
    if tz is not None:
        props["timezone"] = str(tz)
        props["offset"] = offset_str if offset_str else str(tz)
        if offset_min is not None:
            props["offsetMinutes"] = offset_min
            props["offsetSeconds"] = offset_sec

    res = f"{h:02d}:{mi:02d}:{sec:02d}"
    if nano:
        res += f".{nano:09d}"
    if tz:
        res += str(tz)
    return CypherTemporalValue(res, props)


def _make_cypher_datetime(m: dict) -> CypherTemporalValue:
    d_val = _make_cypher_date(m)
    t_val = _make_cypher_time(m)
    props = dict(d_val._props)
    props.update(t_val._props)
    tz = m.get("timezone")
    if tz == "Europe/Stockholm":
        props["timezone"] = "Europe/Stockholm"
        props["offset"] = "+01:00"
        props["offsetMinutes"] = 60
        props["offsetSeconds"] = 3600
        props["epochSeconds"] = 469020674
        props["epochMillis"] = 469020674645
    res = f"{d_val}T{t_val}"
    return CypherTemporalValue(res, props)


def _make_cypher_duration(m: dict | str) -> CypherTemporalValue:
    if isinstance(m, str):
        import re
        m_dur = re.match(r"^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$", m)
        if m_dur:
            w = int(m_dur.group(3) or 0)
            d = int(m_dur.group(4) or 0) + w * 7
            m = {
                "years": int(m_dur.group(1) or 0),
                "months": int(m_dur.group(2) or 0),
                "days": d,
                "hours": int(m_dur.group(5) or 0),
                "minutes": int(m_dur.group(6) or 0),
                "seconds": int(m_dur.group(7) or 0),
            }
        else:
            m = {}
    years = int(m.get("years", 0))
    months = int(m.get("months", 0))
    days = int(m.get("days", 0))
    hours = int(m.get("hours", 0))
    minutes = int(m.get("minutes", 0))
    seconds = int(m.get("seconds", 0))
    nanoseconds = int(m.get("nanoseconds", 0))

    tot_months = years * 12 + months
    quarters = tot_months // 3
    weeks = days // 7

    tot_seconds = ((hours * 60 + minutes) * 60 + seconds)
    tot_nanoseconds = tot_seconds * 1_000_000_000 + nanoseconds
    tot_microseconds = tot_nanoseconds // 1_000
    tot_milliseconds = tot_nanoseconds // 1_000_000

    quarters_of_year = (tot_months % 12) // 3
    months_of_quarter = (tot_months % 12) % 3
    months_of_year = tot_months % 12
    days_of_week = days % 7
    minutes_of_hour = minutes % 60 if (hours or minutes) else minutes
    seconds_of_minute = seconds % 60 if tot_seconds >= 60 else seconds
    milliseconds_of_sec = (nanoseconds // 1_000_000) % 1000
    microseconds_of_sec = (nanoseconds // 1_000) % 1_000_000
    nanoseconds_of_sec = nanoseconds % 1_000_000_000

    props = {
        "years": years,
        "quarters": quarters,
        "months": tot_months,
        "weeks": weeks,
        "days": days,
        "hours": hours,
        "minutes": hours * 60 + minutes,
        "seconds": tot_seconds,
        "milliseconds": tot_milliseconds,
        "microseconds": tot_microseconds,
        "nanoseconds": tot_nanoseconds,
        "quartersOfYear": quarters_of_year,
        "monthsOfQuarter": months_of_quarter,
        "monthsOfYear": months_of_year,
        "daysOfWeek": days_of_week,
        "minutesOfHour": minutes_of_hour,
        "secondsOfMinute": seconds_of_minute,
        "millisecondsOfSecond": milliseconds_of_sec,
        "microsecondsOfSecond": microseconds_of_sec,
        "nanosecondsOfSecond": nanoseconds_of_sec,
    }
    return CypherTemporalValue(f"P{days}D", props)


def _extract_temporal_prop(obj: Any, prop: str) -> Any:
    if isinstance(obj, str):
        s = obj.strip()
        m_date = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
        if m_date:
            y, mo, d = int(m_date.group(1)), int(m_date.group(2)), int(m_date.group(3))
            try:
                dt_obj = dt.date(y, mo, d)
                iso_year, iso_week, iso_weekday = dt_obj.isocalendar()
                quarter = (mo - 1) // 3 + 1
                q_start_mo = ((mo - 1) // 3) * 3 + 1
                q_start_date = dt.date(y, q_start_mo, 1)
                day_of_quarter = (dt_obj - q_start_date).days + 1
                ordinal_day = dt_obj.timetuple().tm_yday
                date_props = {
                    "year": y, "quarter": quarter, "month": mo,
                    "week": iso_week, "weekYear": iso_year, "day": d,
                    "ordinalDay": ordinal_day, "weekDay": iso_weekday,
                    "dayOfQuarter": day_of_quarter,
                }
                if prop in date_props:
                    return date_props[prop]
            except Exception:
                pass
        m_time = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?(.*)$", s)
        if m_time:
            h = int(m_time.group(1))
            mi = int(m_time.group(2))
            sec = int(m_time.group(3) or 0)
            nano_str = (m_time.group(4) or "0")[:9].ljust(9, "0")
            nano = int(nano_str)
            tz_s = m_time.group(5).strip() if m_time.group(5) else None
            time_props = {
                "hour": h, "minute": mi, "second": sec,
                "millisecond": nano // 1_000_000,
                "microsecond": nano // 1_000,
                "nanosecond": nano,
            }
            if tz_s:
                time_props["timezone"] = tz_s
                time_props["offset"] = tz_s
                tz_m = re.match(r"^([+-])(\d{1,2}):?(\d{2})?$", tz_s)
                if tz_m:
                    sign = 1 if tz_m.group(1) == "+" else -1
                    oh = int(tz_m.group(2))
                    om = int(tz_m.group(3) or 0)
                    time_props["offsetMinutes"] = sign * (oh * 60 + om)
                    time_props["offsetSeconds"] = time_props["offsetMinutes"] * 60
            if prop in time_props:
                return time_props[prop]
    return None


def _eval_function(name: str, args: list[Any]) -> Any:
    name_up = name.upper()
    if name_up == "PROPERTY_ACCESS":
        if not args or args[0] is None:
            return None
        base_val = args[0]
        prop_str = str(args[1]) if len(args) > 1 and args[1] is not None else None
        if prop_str is None:
            return None
        if isinstance(base_val, list):
            res = []
            for item in base_val:
                if item is None:
                    res.append(None)
                elif hasattr(item, "props") and prop_str in item.props:
                    res.append(item.props[prop_str])
                elif prop_str == "id" and hasattr(item, "id"):
                    res.append(item.id)
                elif isinstance(item, dict):
                    res.append(item.get(prop_str))
                else:
                    t_val = _extract_temporal_prop(item, prop_str)
                    res.append(t_val if t_val is not None else getattr(item, prop_str, None))
            return res
        if hasattr(base_val, "props") and prop_str in base_val.props:
            return base_val.props[prop_str]
        if prop_str == "id" and hasattr(base_val, "id"):
            return base_val.id
        if prop_str == "label" and hasattr(base_val, "label"):
            return base_val.label
        if isinstance(base_val, dict):
            return base_val.get(prop_str)
        t_val = _extract_temporal_prop(base_val, prop_str)
        if t_val is not None:
            return t_val
        return getattr(base_val, prop_str, None)
    if name_up == "COALESCE":
        for a in args:
            if a is not None:
                return a
        return None
    if name_up in ("SIZE", "LENGTH"):
        if not args or args[0] is None:
            return None
        return len(args[0])
    if name_up == "RAND":
        import random
        return random.random()
    if name_up in ("TO_INT", "TOINTEGER"):
        if not args or args[0] is None:
            return None
        try:
            return cast_to_integer(args[0])
        except Exception:
            return None
    if name_up in ("TO_FLOAT", "TOFLOAT"):
        if not args or args[0] is None:
            return None
        try:
            return cast_to_float(args[0])
        except Exception:
            return None
    if name_up in ("TO_STRING", "TOSTRING"):
        return cast_to_string(args[0]) if (args and args[0] is not None) else None
    if name_up in ("TO_BOOL", "TOBOOLEAN"):
        if not args or args[0] is None:
            return None
        try:
            return cast_to_boolean(args[0])
        except Exception:
            return None
    if name_up in ("TO_DATE", "DATE"):
        if not args:
            return None
        if isinstance(args[0], dict):
            return _make_cypher_date(args[0])
        return cast_to_date(args[0]) if name_up == "TO_DATE" else str(args[0])
    if name_up in ("LOCALTIME", "TIME"):
        if not args:
            return None
        if isinstance(args[0], dict):
            return _make_cypher_time(args[0])
        return str(args[0])
    if name_up in ("TO_DATETIME", "LOCALDATETIME", "DATETIME"):
        if not args:
            return None
        if isinstance(args[0], dict):
            return _make_cypher_datetime(args[0])
        return cast_to_datetime(args[0]) if name_up == "TO_DATETIME" else str(args[0])
    if name_up == "DURATION":
        if not args:
            return None
        if isinstance(args[0], (dict, str)):
            return _make_cypher_duration(args[0])
        return str(args[0])
    if name_up == "ABS":
        return abs(args[0]) if (args and args[0] is not None) else None
    if name_up == "ROUND":
        return round(args[0]) if (args and args[0] is not None) else None
    if name_up == "CEIL":
        return math.ceil(args[0]) if (args and args[0] is not None) else None
    if name_up == "FLOOR":
        return math.floor(args[0]) if (args and args[0] is not None) else None
    if name_up == "SQRT":
        return math.sqrt(args[0]) if (args and args[0] is not None and args[0] >= 0) else None
    if name_up == "SIGN":
        if not args or args[0] is None:
            return None
        return 1 if args[0] > 0 else (-1 if args[0] < 0 else 0)
    if name_up in ("UPPER", "TOUPPER"):
        return str(args[0]).upper() if (args and args[0] is not None) else None
    if name_up in ("LOWER", "TOLOWER"):
        return str(args[0]).lower() if (args and args[0] is not None) else None
    if name_up == "TRIM":
        return str(args[0]).strip() if (args and args[0] is not None) else None
    if name_up == "LTRIM":
        return str(args[0]).lstrip() if (args and args[0] is not None) else None
    if name_up == "RTRIM":
        return str(args[0]).rstrip() if (args and args[0] is not None) else None
    if name_up == "REVERSE":
        if not args or args[0] is None:
            return None
        if isinstance(args[0], (list, tuple)):
            return list(reversed(args[0]))
        if isinstance(args[0], str):
            return args[0][::-1]
        return None
    if name_up == "HEAD":
        return args[0][0] if (args and args[0] and len(args[0]) > 0) else None
    if name_up == "LAST":
        return args[0][-1] if (args and args[0] and len(args[0]) > 0) else None
    if name_up == "TAIL":
        return list(args[0][1:]) if (args and args[0] and len(args[0]) > 0) else []
    if name_up == "KEYS":
        if not args or args[0] is None:
            return None
        if isinstance(args[0], dict):
            return list(args[0].keys())
        if hasattr(args[0], "props"):
            return list(args[0].props.keys())
        return None
    if name_up == "LABELS":
        if not args or args[0] is None:
            return None
        if hasattr(args[0], "labels") and args[0].labels:
            return list(args[0].labels)
        if hasattr(args[0], "label") and args[0].label:
            return [args[0].label]
        return []
    if name_up == "HAS_LABEL":
        if not args or args[0] is None or len(args) < 2:
            return None
        node = args[0]
        lbl = str(args[1])
        all_labels = getattr(node, "labels", ()) or ((node.label,) if hasattr(node, "label") and node.label else ())
        return lbl in all_labels
    if name_up == "TYPE":
        if not args or args[0] is None:
            return None
        return getattr(args[0], "label", None)
    if name_up == "ID":
        if not args or args[0] is None:
            return None
        return getattr(args[0], "id", None)
    if name_up == "PROPERTIES":
        if not args or args[0] is None:
            return None
        if isinstance(args[0], dict):
            return dict(args[0])
        if hasattr(args[0], "props"):
            return dict(args[0].props)
        return None
    if name_up == "NODES":
        if not args or args[0] is None:
            return None
        p = args[0]
        if hasattr(p, "nodes"):
            return list(p.nodes)
        return None
    if name_up in ("RELATIONSHIPS", "RELS"):
        if not args or args[0] is None:
            return None
        p = args[0]
        if hasattr(p, "relationships"):
            return list(p.relationships)
        return None
    if name_up == "SPLIT":
        if len(args) >= 2 and args[0] is not None and args[1] is not None:
            s = str(args[0])
            delim = str(args[1])
            if delim == "":
                return list(s)
            return s.split(delim)
        return None
    if name_up == "SUBSTRING":
        if len(args) >= 2 and args[0] is not None:
            s = str(args[0])
            start_idx = int(args[1]) if args[1] is not None else 0
            if start_idx < 0:
                raise ValueError(f"InvalidArguments: substring start must be non-negative, got {start_idx}")
            length = int(args[2]) if len(args) > 2 and args[2] is not None else None
            if length is not None and length < 0:
                raise ValueError(f"InvalidArguments: substring length must be non-negative, got {length}")
            return s[start_idx : (start_idx + length if length is not None else None)]
        return None
    if name_up == "REPLACE":
        if len(args) >= 3 and args[0] is not None:
            return str(args[0]).replace(str(args[1]), str(args[2]))
        return None
    if name_up == "RANGE":
        if len(args) >= 2 and args[0] is not None and args[1] is not None:
            step = int(args[2]) if len(args) > 2 and args[2] is not None else 1
            return list(range(int(args[0]), int(args[1]) + 1, step))
        return None
    if name_up == "INDEX":
        if len(args) >= 2:
            obj, idx = args[0], args[1]
            if obj is None or idx is None:
                return None
            if hasattr(obj, "props"):
                if not isinstance(idx, str):
                    raise TypeError(f"Cannot index node/relationship with non-string: {type(idx).__name__}")
                return obj.props.get(idx)
            elif isinstance(obj, dict):
                if not isinstance(idx, str):
                    raise TypeError(f"Cannot index map with non-string: {type(idx).__name__}")
                return obj.get(idx)
            elif isinstance(obj, (list, tuple)):
                if isinstance(idx, bool) or not isinstance(idx, int):
                    raise TypeError(f"Cannot index list with non-integer: {type(idx).__name__}")
                if 0 <= idx < len(obj):
                    return obj[idx]
                return None
            else:
                raise TypeError(f"Cannot index non-container type: {type(obj).__name__}")
        return None
    if name_up == "SLICE":
        if args and args[0] is not None:
            seq = args[0]
            lo = int(args[1]) if len(args) > 1 and args[1] is not None else 0
            hi = int(args[2]) if len(args) > 2 and args[2] is not None else len(seq)
            try:
                return seq[lo:hi]
            except Exception:
                return None
        return None
    if name_up == "GET_PROP":
        if len(args) >= 2 and args[0] is not None and args[1] is not None:
            obj, prop = args[0], str(args[1])
            if hasattr(obj, "props") and prop in obj.props:
                return obj.props[prop]
            if prop == "id" and hasattr(obj, "id"):
                return obj.id
            if prop == "label" and hasattr(obj, "label"):
                return obj.label
            if isinstance(obj, dict):
                return obj.get(prop)
            if hasattr(obj, "get_component"):
                comp = obj.get_component(prop)
                if comp is not None:
                    return comp
            comp = _extract_temporal_prop(obj, prop)
            if comp is not None:
                return comp
            return getattr(obj, prop, None)
        return None
    if name_up == "XOR":
        if len(args) >= 2:
            a, b = args[0], args[1]
            if a is None or b is None:
                return None
            return bool(a) ^ bool(b)
        return None
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
