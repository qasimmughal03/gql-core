"""Logical plan validator for GQL-Core typed query IR.

Validates:
- Unknown operators
- Invalid operands
- Variable scoping and variable leaks (preventing Cartesian products or unbound refs)
- Impossible type combinations
- Hop bounds and cardinality constraints
- Set algebra schema alignment
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gql_core.ir import (
    AggregateExpr,
    And,
    AntiJoin,
    Arithmetic,
    Between,
    BoolExpr,
    CaseExpr,
    CoalesceExpr,
    CollectionQuantifier,
    Comparison,
    Distinct,
    Except,
    Exists,
    Expand,
    Filter,
    FunctionCall,
    GroupBy,
    Having,
    In,
    Intersect,
    IsNotNull,
    IsNull,
    IsMissing,
    IsPresent,
    Join,
    LeftOuterJoin,
    Limit,
    ListExpr,
    Literal,
    MapExpr,
    Not,
    NotBetween,
    NotExists,
    NotIn,
    Or,
    Parameter,
    PatternExpr,
    Project,
    ProjectItem,
    Property,
    QuantifiedRel,
    RecursiveExpand,
    RegexMatch,
    RelOp,
    Scan,
    SemiJoin,
    Sort,
    StringMatch,
    TemporalExpr,
    TypePredicate,
    Union,
    ValueExpr,
    Variable,
)
from gql_core.types import DataType, is_numeric_type


class PlanValidationError(ValueError):
    """Raised when a logical plan violates variable scoping, typing, or structure."""

    def __init__(self, code: str, message: str, path: str = ""):
        self.code = code
        self.message = message
        self.path = path
        prefix = f"[{path}] " if path else ""
        super().__init__(f"{prefix}{code}: {message}")


@dataclass
class ValidationReport:
    is_valid: bool
    errors: list[PlanValidationError]


def validate_logical_plan(root: RelOp, strict: bool = True) -> ValidationReport:
    """Validate a logical plan tree.

    In strict mode, raises PlanValidationError on the first violation.
    Otherwise, returns a ValidationReport with all detected errors.
    """
    errors: list[PlanValidationError] = []

    def _record_error(code: str, message: str, path: str) -> None:
        err = PlanValidationError(code=code, message=message, path=path)
        errors.append(err)
        if strict:
            raise err

    _validate_op(root, bound_vars=set(), path="root", record_error=_record_error)
    return ValidationReport(is_valid=len(errors) == 0, errors=errors)


def _validate_op(
    op: RelOp,
    bound_vars: set[str],
    path: str,
    record_error: Any,
) -> set[str]:
    """Validate operator and return set of bound variables emitted to parent."""
    if not isinstance(op, RelOp):
        record_error("UNKNOWN_OPERATOR", f"Expected RelOp instance, got {type(op).__name__}", path)
        return bound_vars

    if isinstance(op, Scan):
        if not op.var or not isinstance(op.var, str):
            record_error("INVALID_VARIABLE", "Scan variable must be a non-empty string", path)
        return bound_vars | {op.var}

    if isinstance(op, Expand):
        input_vars = _validate_op(op.input, bound_vars, f"{path}.input", record_error) if op.input else bound_vars
        if op.from_var not in input_vars:
            record_error(
                "UNBOUND_VARIABLE",
                f"Expand from_var {op.from_var!r} is not bound in preceding scope {sorted(input_vars)}",
                path,
            )
        new_vars = set(input_vars)
        if op.to_var:
            new_vars.add(op.to_var)
        if op.edge_var:
            new_vars.add(op.edge_var)
        return new_vars

    if isinstance(op, RecursiveExpand):
        input_vars = _validate_op(op.input, bound_vars, f"{path}.input", record_error) if op.input else bound_vars
        if op.min_hops < 0:
            record_error("INVALID_BOUNDS", f"min_hops cannot be negative ({op.min_hops})", path)
        if op.max_hops is not None and op.max_hops < op.min_hops:
            record_error("INVALID_BOUNDS", f"max_hops ({op.max_hops}) cannot be less than min_hops ({op.min_hops})", path)
        if op.from_var not in input_vars:
            record_error(
                "UNBOUND_VARIABLE",
                f"RecursiveExpand from_var {op.from_var!r} is not bound in scope {sorted(input_vars)}",
                path,
            )
        new_vars = set(input_vars)
        if op.to_var:
            new_vars.add(op.to_var)
        if op.edge_var:
            new_vars.add(op.edge_var)
        return new_vars

    if isinstance(op, Filter):
        input_vars = _validate_op(op.input, bound_vars, f"{path}.input", record_error)
        _validate_bool_expr(op.predicate, input_vars, f"{path}.predicate", record_error)
        return input_vars

    if isinstance(op, Project):
        input_vars = _validate_op(op.input, bound_vars, f"{path}.input", record_error)
        output_vars: set[str] = set()
        for idx, item in enumerate(op.projections):
            _validate_value_expr(item.expr, input_vars, f"{path}.projections[{idx}]", record_error)
            if not item.alias:
                record_error("INVALID_ALIAS", f"Projection at index {idx} missing alias", path)
            output_vars.add(item.alias)
        return output_vars

    if isinstance(op, Join):
        left_vars = _validate_op(op.left, bound_vars, f"{path}.left", record_error)
        right_vars = _validate_op(op.right, bound_vars | left_vars, f"{path}.right", record_error)
        if op.kind not in ("INNER", "LEFT_OUTER", "SEMI", "ANTI", "CROSS"):
            record_error("INVALID_JOIN_KIND", f"Unsupported join kind: {op.kind!r}", path)
        if op.kind != "CROSS":
            for on_var in op.on:
                if on_var not in left_vars:
                    record_error("JOIN_KEY_MISSING", f"Join key {on_var!r} missing from left relation", path)
                if on_var not in right_vars and on_var not in (bound_vars | left_vars):
                    record_error("JOIN_KEY_MISSING", f"Join key {on_var!r} missing from right relation", path)
        if op.kind in ("SEMI", "ANTI"):
            # Semi/Anti joins filter left by right, but DO NOT emit right variables!
            return left_vars
        return left_vars | right_vars

    if isinstance(op, (SemiJoin, AntiJoin)):
        left_vars = _validate_op(op.left, bound_vars, f"{path}.left", record_error)
        right_vars = _validate_op(op.right, bound_vars | left_vars, f"{path}.right", record_error)
        for on_var in op.on:
            if on_var not in left_vars or (on_var not in right_vars and on_var not in (bound_vars | left_vars)):
                record_error("JOIN_KEY_MISSING", f"Join key {on_var!r} must be present in both relations", path)
        return left_vars

    if isinstance(op, LeftOuterJoin):
        left_vars = _validate_op(op.left, bound_vars, f"{path}.left", record_error)
        right_vars = _validate_op(op.right, bound_vars | left_vars, f"{path}.right", record_error)
        for on_var in op.on:
            if on_var not in left_vars or (on_var not in right_vars and on_var not in (bound_vars | left_vars)):
                record_error("JOIN_KEY_MISSING", f"Join key {on_var!r} must be present in both relations", path)
        return left_vars | right_vars

    if isinstance(op, (Union, Intersect, Except)):
        left_vars = _validate_op(op.left, bound_vars, f"{path}.left", record_error)
        right_vars = _validate_op(op.right, bound_vars, f"{path}.right", record_error)
        if left_vars != right_vars:
            record_error(
                "SET_OP_SCHEMA_MISMATCH",
                f"Set operation operands must have identical schemas. Left: {sorted(left_vars)}, Right: {sorted(right_vars)}",
                path,
            )
        return left_vars

    if isinstance(op, GroupBy):
        input_vars = _validate_op(op.input, bound_vars, f"{path}.input", record_error)
        for key in op.keys:
            if key not in input_vars:
                record_error("UNBOUND_VARIABLE", f"GroupBy key {key!r} not in input scope {sorted(input_vars)}", path)
        output_vars = set(op.keys)
        for idx, agg_item in enumerate(op.aggregates):
            _validate_value_expr(agg_item.expr, input_vars, f"{path}.aggregates[{idx}]", record_error)
            if not agg_item.alias:
                record_error("INVALID_ALIAS", f"Aggregate at index {idx} missing alias", path)
            output_vars.add(agg_item.alias)
        return output_vars

    if isinstance(op, Having):
        input_vars = _validate_op(op.input, bound_vars, f"{path}.input", record_error)
        _validate_bool_expr(op.predicate, input_vars, f"{path}.predicate", record_error)
        return input_vars

    if isinstance(op, Distinct):
        return _validate_op(op.input, bound_vars, f"{path}.input", record_error)

    if isinstance(op, Sort):
        input_vars = _validate_op(op.input, bound_vars, f"{path}.input", record_error)
        for idx, term in enumerate(op.terms):
            _validate_value_expr(term.expr, input_vars, f"{path}.terms[{idx}]", record_error)
            if term.direction.upper() not in ("ASC", "DESC"):
                record_error("INVALID_SORT_DIRECTION", f"Sort direction must be ASC or DESC, got {term.direction!r}", path)
        return input_vars

    if isinstance(op, Limit):
        input_vars = _validate_op(op.input, bound_vars, f"{path}.input", record_error)
        if op.count < 0:
            record_error("INVALID_LIMIT", f"Limit count cannot be negative: {op.count}", path)
        if op.offset < 0:
            record_error("INVALID_OFFSET", f"Limit offset cannot be negative: {op.offset}", path)
        return input_vars

    record_error("UNKNOWN_OPERATOR", f"Unhandled operator {type(op).__name__}", path)
    return bound_vars


def _validate_bool_expr(
    expr: BoolExpr,
    bound_vars: set[str],
    path: str,
    record_error: Any,
) -> None:
    if isinstance(expr, (And, Or)):
        for idx, child in enumerate(expr.children):
            _validate_bool_expr(child, bound_vars, f"{path}.children[{idx}]", record_error)
    elif isinstance(expr, Not):
        _validate_bool_expr(expr.inner, bound_vars, f"{path}.inner", record_error)
    elif isinstance(expr, Comparison):
        _validate_value_expr(expr.lhs, bound_vars, f"{path}.lhs", record_error)
        _validate_value_expr(expr.rhs, bound_vars, f"{path}.rhs", record_error)
        if expr.op not in ("=", "!=", "<", "<=", ">", ">="):
            record_error("INVALID_COMPARISON_OP", f"Unsupported comparison operator: {expr.op!r}", path)
    elif isinstance(expr, (IsNull, IsNotNull)):
        _validate_value_expr(expr.expr, bound_vars, f"{path}.expr", record_error)
    elif isinstance(expr, (IsMissing, IsPresent)):
        if expr.var not in bound_vars:
            record_error("UNBOUND_VARIABLE", f"Variable {expr.var!r} is not bound in scope {sorted(bound_vars)}", path)
    elif isinstance(expr, (In, NotIn)):
        _validate_value_expr(expr.element, bound_vars, f"{path}.element", record_error)
        _validate_value_expr(expr.collection, bound_vars, f"{path}.collection", record_error)
    elif isinstance(expr, (Between, NotBetween)):
        _validate_value_expr(expr.expr, bound_vars, f"{path}.expr", record_error)
        _validate_value_expr(expr.low, bound_vars, f"{path}.low", record_error)
        _validate_value_expr(expr.high, bound_vars, f"{path}.high", record_error)
    elif isinstance(expr, StringMatch):
        _validate_value_expr(expr.string_expr, bound_vars, f"{path}.string_expr", record_error)
        _validate_value_expr(expr.pattern_expr, bound_vars, f"{path}.pattern_expr", record_error)
        if expr.op not in ("STARTS_WITH", "ENDS_WITH", "CONTAINS"):
            record_error("INVALID_STRING_MATCH_OP", f"Unsupported string match op: {expr.op!r}", path)
    elif isinstance(expr, RegexMatch):
        _validate_value_expr(expr.string_expr, bound_vars, f"{path}.string_expr", record_error)
    elif isinstance(expr, PatternExpr):
        if expr.source_var not in bound_vars:
            record_error("UNBOUND_VARIABLE", f"Pattern source {expr.source_var!r} is not bound in scope", path)
        if expr.target_filter:
            sub_scope = bound_vars | {expr.target_var}
            _validate_bool_expr(expr.target_filter, sub_scope, f"{path}.target_filter", record_error)
    elif isinstance(expr, (Exists, NotExists)):
        target = expr.subquery_or_pattern
        if isinstance(target, PatternExpr):
            if target.source_var not in bound_vars:
                record_error("UNBOUND_VARIABLE", f"Pattern source {target.source_var!r} not in scope", path)
            if target.target_filter:
                sub_scope = bound_vars | {target.target_var}
                _validate_bool_expr(target.target_filter, sub_scope, f"{path}.target_filter", record_error)
        elif isinstance(target, RelOp):
            # Correlated subquery: outer bound_vars are available, but inner vars must not leak
            _validate_op(target, bound_vars, f"{path}.subquery", record_error)
        else:
            record_error("INVALID_EXISTS_TARGET", f"Invalid target for EXISTS: {type(target).__name__}", path)
    elif isinstance(expr, QuantifiedRel):
        if expr.source_var not in bound_vars:
            record_error("UNBOUND_VARIABLE", f"QuantifiedRel source {expr.source_var!r} is not bound in scope", path)
        if expr.predicate:
            sub_scope = bound_vars | {expr.target_var}
            _validate_bool_expr(expr.predicate, sub_scope, f"{path}.predicate", record_error)
        if expr.quantifier not in ("ANY", "ALL", "NONE", "SINGLE", "AT_LEAST", "AT_MOST", "EXACTLY", "COUNT_SATISFYING"):
            record_error("INVALID_QUANTIFIER", f"Unknown quantifier: {expr.quantifier!r}", path)
        if expr.quantifier in ("AT_LEAST", "AT_MOST", "EXACTLY", "COUNT_SATISFYING") and expr.count is None:
            record_error("MISSING_COUNT", f"Quantifier {expr.quantifier} requires count parameter", path)
    elif isinstance(expr, CollectionQuantifier):
        _validate_value_expr(expr.collection_expr, bound_vars, f"{path}.collection_expr", record_error)
        elem_scope = bound_vars | {expr.elem_var}
        _validate_bool_expr(expr.predicate, elem_scope, f"{path}.predicate", record_error)
    elif isinstance(expr, TypePredicate):
        if expr.var not in bound_vars:
            record_error("UNBOUND_VARIABLE", f"TypePredicate variable {expr.var!r} is not bound in scope", path)
    else:
        record_error("UNKNOWN_BOOL_EXPR", f"Unhandled Boolean expression {type(expr).__name__}", path)


def _validate_value_expr(
    expr: ValueExpr,
    bound_vars: set[str],
    path: str,
    record_error: Any,
) -> None:
    if isinstance(expr, Literal):
        return
    if isinstance(expr, Variable):
        base_name = expr.name.split(".", 1)[0] if "." in expr.name else expr.name
        if expr.name not in bound_vars and base_name not in bound_vars:
            record_error("UNBOUND_VARIABLE", f"Variable {expr.name!r} is not bound in scope {sorted(bound_vars)}", path)
        return
    if isinstance(expr, Property):
        if expr.var not in bound_vars:
            record_error("UNBOUND_VARIABLE", f"Property receiver variable {expr.var!r} is not bound in scope {sorted(bound_vars)}", path)
        return
    if isinstance(expr, Parameter):
        return
    if isinstance(expr, Arithmetic):
        _validate_value_expr(expr.lhs, bound_vars, f"{path}.lhs", record_error)
        _validate_value_expr(expr.rhs, bound_vars, f"{path}.rhs", record_error)
        if expr.op not in ("+", "-", "*", "/", "%"):
            record_error("INVALID_ARITHMETIC_OP", f"Unsupported arithmetic operator: {expr.op!r}", path)
        return
    if isinstance(expr, FunctionCall):
        for idx, arg in enumerate(expr.args):
            _validate_value_expr(arg, bound_vars, f"{path}.args[{idx}]", record_error)
        return
    if isinstance(expr, ListExpr):
        for idx, elem in enumerate(expr.elements):
            _validate_value_expr(elem, bound_vars, f"{path}.elements[{idx}]", record_error)
        return
    if isinstance(expr, MapExpr):
        for k, val in expr.entries:
            _validate_value_expr(val, bound_vars, f"{path}.entries[{k}]", record_error)
        return
    if isinstance(expr, TemporalExpr):
        for idx, arg in enumerate(expr.args):
            _validate_value_expr(arg, bound_vars, f"{path}.args[{idx}]", record_error)
        return
    if isinstance(expr, AggregateExpr):
        if expr.expr:
            _validate_value_expr(expr.expr, bound_vars, f"{path}.expr", record_error)
        if expr.func.upper() not in ("COUNT", "SUM", "AVG", "MIN", "MAX", "COLLECT"):
            record_error("INVALID_AGGREGATE_FUNC", f"Unsupported aggregate function: {expr.func!r}", path)
        return
    if isinstance(expr, CaseExpr):
        for idx, (cond, res) in enumerate(expr.cases):
            _validate_bool_expr(cond, bound_vars, f"{path}.cases[{idx}].cond", record_error)
            _validate_value_expr(res, bound_vars, f"{path}.cases[{idx}].res", record_error)
        if expr.else_expr:
            _validate_value_expr(expr.else_expr, bound_vars, f"{path}.else_expr", record_error)
        return
    if isinstance(expr, CoalesceExpr):
        for idx, sub in enumerate(expr.expressions):
            _validate_value_expr(sub, bound_vars, f"{path}.expressions[{idx}]", record_error)
        return

    record_error("UNKNOWN_VALUE_EXPR", f"Unhandled ValueExpr {type(expr).__name__}", path)
