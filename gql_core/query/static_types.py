"""Compile-time static type and scope checks for openCypher queries.

Only *definite* type errors are reported: an expression whose static type is
unknown (``"any"``) never triggers an error. This keeps the checker sound with
respect to valid queries while rejecting the invalid queries the openCypher
TCK requires to fail at compile time (TypeMismatch / InvalidArgumentType /
UndefinedVariable / InvalidAggregation / VariableTypeConflict).
"""

from __future__ import annotations

from typing import Any

from gql_core.ir import (
    And as IRAnd,
    Arithmetic,
    CaseExpr,
    Comparison as IRComparison,
    FunctionCall,
    In as IRIn,
    ListExpr,
    Literal,
    MapExpr,
    Not as IRNot,
    NotIn as IRNotIn,
    Or as IROr,
    Parameter,
    Property,
    Variable,
)
from gql_core.query.ast import (
    And as ASTAnd,
    CallClause,
    CallSubquery,
    Comparison as ASTComparison,
    CreateClause,
    MatchClause,
    MergeClause,
    Not as ASTNot,
    Or as ASTOr,
    PatternPredicate,
    Projection,
    Ref,
    ReturnClause,
    UnwindClause,
    WithClause,
)

ANY = "any"
_NON_BOOLEAN = {"int", "float", "string", "list", "map", "node", "edge", "path"}
_SCALARS_AND_LISTS = {"int", "float", "string", "boolean", "list"}
_AGGREGATES = {"COUNT", "SUM", "AVG", "MIN", "MAX", "COLLECT", "PERCENTILEDISC", "PERCENTILECONT"}


def _py_type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "string"
    if isinstance(v, (list, tuple)):
        return "list"
    if isinstance(v, dict):
        return "map"
    return ANY


def _is_expr(e: Any) -> bool:
    return hasattr(e, "__dataclass_fields__")


def _elem_type(coll: Any, scope: dict[str, str]) -> str:
    if isinstance(coll, ListExpr) and coll.elements:
        ts = {_t(e, scope) for e in coll.elements}
        if len(ts) == 1:
            t = ts.pop()
            return t if t != "null" else ANY
    if isinstance(coll, Literal) and isinstance(coll.value, (list, tuple)) and coll.value:
        ts = {_py_type(v) for v in coll.value}
        if len(ts) == 1:
            t = ts.pop()
            return t if t != "null" else ANY
    return ANY


def _contains_aggregate(e: Any) -> bool:
    if isinstance(e, Projection):
        return e.agg is not None or _contains_aggregate(e.expr)
    if isinstance(e, FunctionCall):
        if e.name.upper() in _AGGREGATES:
            return True
        return any(_contains_aggregate(a) for a in e.args if _is_expr(a))
    if not _is_expr(e):
        return False
    for f in e.__dataclass_fields__:
        v = getattr(e, f)
        if isinstance(v, (list, tuple)):
            if any(_contains_aggregate(x) for x in v if _is_expr(x)):
                return True
        elif _is_expr(v) and _contains_aggregate(v):
            return True
    return False


def _free_vars(e: Any, out: set[str]) -> None:
    if isinstance(e, Ref):
        if not e.var.startswith("$") and e.var != "*":
            out.add(e.var)
        return
    if isinstance(e, Variable):
        out.add(e.name)
        return
    if isinstance(e, (Property,)):
        out.add(e.var)
        return
    if isinstance(e, FunctionCall):
        name = e.name.upper()
        if name in ("ALL", "ANY", "NONE", "SINGLE", "LIST_COMPREHENSION", "PATTERN_COMPREHENSION", "EXISTS"):
            return  # introduces local scope; skip conservatively
        for a in e.args:
            if _is_expr(a):
                _free_vars(a, out)
        return
    if isinstance(e, (PatternPredicate, Parameter, Literal)) or not _is_expr(e):
        return
    for f in e.__dataclass_fields__:
        v = getattr(e, f)
        if isinstance(v, (list, tuple)):
            for x in v:
                if _is_expr(x):
                    _free_vars(x, out)
                elif isinstance(x, tuple):
                    for y in x:
                        if _is_expr(y):
                            _free_vars(y, out)
        elif _is_expr(v):
            _free_vars(v, out)


def _check_bool_operands(types: list[str]) -> None:
    for t in types:
        if t in _NON_BOOLEAN:
            raise SyntaxError(f"InvalidArgumentType: expected Boolean operand, got {t}")


def _t(e: Any, scope: dict[str, str]) -> str:  # noqa: C901
    if e is None:
        return "null"
    if not _is_expr(e):
        return _py_type(e)
    if isinstance(e, Literal):
        return _py_type(e.value)
    if isinstance(e, Parameter):
        return ANY
    if isinstance(e, Variable):
        return scope.get(e.name, ANY)
    if isinstance(e, Ref):
        if e.var.startswith("$"):
            return ANY
        base = scope.get(e.var, ANY)
        if e.prop is None:
            return base
        if base in _SCALARS_AND_LISTS:
            raise TypeError(f"InvalidArgumentType: cannot access property '{e.prop}' on {base}")
        return ANY
    if isinstance(e, Property):
        base = scope.get(e.var, ANY)
        if base in _SCALARS_AND_LISTS:
            raise TypeError(f"InvalidArgumentType: cannot access property '{e.prop}' on {base}")
        return ANY
    if isinstance(e, (ASTAnd, IRAnd, ASTOr, IROr)):
        _check_bool_operands([_t(c, scope) for c in e.children])
        return "boolean"
    if isinstance(e, (ASTNot, IRNot)):
        _check_bool_operands([_t(e.inner, scope)])
        return "boolean"
    if isinstance(e, (ASTComparison, IRComparison)):
        _t(e.lhs, scope)
        _t(e.rhs, scope)
        return "boolean"
    if isinstance(e, (IRIn, IRNotIn)):
        _t(e.element, scope)
        ct = _t(e.collection, scope)
        if ct in ("int", "float", "string", "boolean", "map", "node", "edge", "path"):
            raise SyntaxError(f"InvalidArgumentType: IN requires a list, got {ct}")
        return "boolean"
    if isinstance(e, Arithmetic):
        lt, rt = _t(e.lhs, scope), _t(e.rhs, scope)
        if e.op == "+" and "list" in (lt, rt):
            return "list"
        for t in (lt, rt):
            if t in ("boolean", "node", "edge", "path", "map"):
                raise SyntaxError(f"InvalidArgumentType: '{e.op}' not applicable to {t}")
            if e.op != "+" and t in ("string", "list"):
                raise SyntaxError(f"InvalidArgumentType: '{e.op}' not applicable to {t}")
        if e.op == "+" and "list" in (lt, rt):
            return "list"
        if e.op == "+" and lt == rt == "string":
            return "string"
        if lt == rt == "int":
            return "int"
        if {lt, rt} <= {"int", "float"}:
            return "float"
        return ANY
    if isinstance(e, ListExpr):
        for x in e.elements:
            _t(x, scope)
        return "list"
    if isinstance(e, MapExpr):
        for _, v in e.entries:
            _t(v, scope)
        return "map"
    if isinstance(e, CaseExpr):
        for c, r in e.cases:
            _t(c, scope)
            _t(r, scope)
        if e.else_expr is not None:
            _t(e.else_expr, scope)
        return ANY
    if isinstance(e, PatternPredicate):
        _check_pattern_predicate(e, scope)
        return "boolean"
    if isinstance(e, Projection):
        if e.expr is not None and not (isinstance(e.expr, Ref) and e.expr.var == "*"):
            _t(e.expr, scope)
        if e.agg:
            return {"COUNT": "int", "COLLECT": "list"}.get(e.agg.upper(), ANY)
        return ANY
    if isinstance(e, FunctionCall):
        return _t_func(e, scope)
    # Any other expression: recurse into dataclass children conservatively
    for f in e.__dataclass_fields__:
        v = getattr(e, f)
        if _is_expr(v):
            _t(v, scope)
    return ANY


def _t_func(e: FunctionCall, scope: dict[str, str]) -> str:
    name = e.name.upper()
    args = list(e.args)
    if name in ("ALL", "ANY", "NONE", "SINGLE", "LIST_COMPREHENSION") and len(args) >= 2:
        var = args[0]
        vname = getattr(var, "name", getattr(var, "var", str(var)))
        _t(args[1], scope)
        inner = dict(scope)
        inner[vname] = _elem_type(args[1], scope)
        for a in args[2:]:
            if _is_expr(a):
                _t(a, inner)
        return "boolean" if name != "LIST_COMPREHENSION" else "list"
    if name in ("PATTERN_COMPREHENSION", "EXISTS"):
        return "list" if name == "PATTERN_COMPREHENSION" else "boolean"
    if name == "XOR":
        _check_bool_operands([_t(a, scope) for a in args])
        return "boolean"
    if name == "SIZE" and args and isinstance(args[0], PatternPredicate):
        raise SyntaxError("InvalidArgumentType: size() of a pattern expression is not allowed")
    types = [_t(a, scope) if _is_expr(a) or a is None or isinstance(a, (bool, int, float, str)) else ANY for a in args]
    if name == "LABELS" and types and types[0] not in ("node", ANY, "null"):
        raise SyntaxError(f"InvalidArgumentType: labels() expects a node, got {types[0]}")
    if name == "PROPERTIES" and types and types[0] in ("int", "float", "string", "boolean", "list", "path"):
        raise SyntaxError(f"InvalidArgumentType: properties() expects a node, relationship or map, got {types[0]}")
    if name == "COUNT":
        return "int"
    if name in ("COLLECT", "LABELS", "KEYS", "NODES", "RELATIONSHIPS", "RANGE", "SPLIT", "TAIL", "REVERSE"):
        return "list" if name != "REVERSE" else ANY
    return ANY


def _pattern_vars(pattern: Any) -> list[str]:
    out = []
    for n in pattern.nodes:
        if n.var:
            out.append(n.var)
    for r in pattern.rels:
        if r.var:
            out.append(r.var)
    return out


def _check_pattern_predicate(pp: PatternPredicate, scope: dict[str, str]) -> None:
    if pp.subquery:
        return  # EXISTS { ... } may introduce variables local to the subquery
    for v in _pattern_vars(pp.pattern):
        if v.startswith("__anon"):
            continue
        if v not in scope:
            raise SyntaxError(f"UndefinedVariable: pattern expressions cannot introduce new variable '{v}'")


def _bind_patterns(patterns: Any, scope: dict[str, str], check_existing: bool = True) -> None:
    local: dict[str, str] = {}

    def claim(var: str | None, kind: str) -> None:
        if not var:
            return
        prev = local.get(var)
        if prev is not None and prev != kind:
            raise SyntaxError(f"VariableTypeConflict: '{var}' used as both {prev} and {kind}")
        local[var] = kind

    for pat in patterns:
        for n in pat.nodes:
            claim(n.var, "node")
        for r in pat.rels:
            claim(r.var, "edge" if tuple(r.quantifier) == ("one",) else "list")
        if getattr(pat, "path_var", None):
            claim(pat.path_var, "path")
    for var, kind in local.items():
        if check_existing and var in scope:
            prev = scope[var]
            if prev not in (ANY, kind, "null"):
                raise SyntaxError(f"VariableTypeConflict: '{var}' is already bound to {prev}, cannot rebind as {kind}")
            if kind == "path" and prev == "path":
                raise SyntaxError(f"VariableAlreadyBound: path variable '{var}' is already bound")
        if scope.get(var, ANY) == ANY or var not in scope:
            scope[var] = kind


def check_static_types(query: Any) -> None:
    clauses = list(getattr(query, "clauses", ()) or ())
    if not clauses:
        return
    scope: dict[str, str] = {}
    for cl in clauses:
        if isinstance(cl, MatchClause):
            _bind_patterns(cl.patterns, scope)
            if cl.where is not None:
                _t(cl.where, scope)
        elif isinstance(cl, (CreateClause,)):
            _bind_patterns(cl.patterns, scope, check_existing=False)
        elif isinstance(cl, MergeClause):
            _bind_patterns((cl.pattern,), scope, check_existing=False)
        elif isinstance(cl, UnwindClause):
            _t(cl.expr, scope)
            scope[cl.alias] = _elem_type(cl.expr, scope)
        elif isinstance(cl, CallSubquery):
            ret = next((c for c in reversed(cl.query.clauses) if isinstance(c, ReturnClause)), None)
            for p in (ret.items if ret else ()):
                if p.alias:
                    scope[p.alias] = ANY
                elif isinstance(p.expr, Ref) and p.expr.prop is None:
                    scope[p.expr.var] = ANY
                elif type(p.expr).__name__ == "Variable":
                    scope[p.expr.name] = ANY
        elif isinstance(cl, CallClause):
            for a in cl.args:
                if _is_expr(a):
                    _t(a, scope)
            for orig, alias in cl.yield_items or ():
                if orig != "*":
                    scope[alias or orig] = ANY
        elif isinstance(cl, WithClause):
            new_scope: dict[str, str] = {}
            star = False
            aggregating = False
            for p in cl.items:
                if p.agg is None and ((isinstance(p.expr, Ref) and p.expr.var == "*") or getattr(p, "raw_expr", "") == "*"):
                    star = True
                    continue
                if p.agg is not None or _contains_aggregate(p.expr):
                    aggregating = True
                t = _t(p, scope) if p.agg else _t(p.expr, scope)
                key = p.alias or (p.expr.var if isinstance(p.expr, Ref) and p.expr.prop is None else getattr(p.expr, "name", None))
                if key:
                    new_scope[key] = t
            if star:
                merged = dict(scope)
                merged.update(new_scope)
                new_scope = merged
            if cl.order_by is not None:
                visible = {**scope, **new_scope}
                for term in cl.order_by.terms:
                    if not aggregating and _contains_aggregate(term.ref):
                        raise SyntaxError("InvalidAggregation: aggregation in ORDER BY of a non-aggregating WITH")
                    fv: set[str] = set()
                    _free_vars(term.ref, fv)
                    for v in fv:
                        if v not in visible:
                            raise SyntaxError(f"UndefinedVariable: '{v}' is not defined in ORDER BY")
                    if not _contains_aggregate(term.ref):
                        _t(term.ref, visible)
            if cl.where is not None:
                _t(cl.where, {**scope, **new_scope})
            scope = new_scope
        elif isinstance(cl, ReturnClause):
            for p in cl.items:
                if p.agg is None and ((isinstance(p.expr, Ref) and p.expr.var == "*") or getattr(p, "raw_expr", "") == "*"):
                    continue
                if p.agg:
                    _t(p, scope)
                else:
                    _t(p.expr, scope)
