"""Semantic validation for GQL-Core queries.

The Lark grammar proves syntax only. This pass checks the parts of the
query that need schema knowledge: variables must be bound, known labels must
use known properties, and labelled relationships must be used with compatible
endpoint labels.

When a schema_path is provided, full schema-aware validation runs. Without
one, only structural checks (unbound variables, conflicting labels) are
performed — the engine carries no embedded domain ontology.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gql_core.query.ast import (
    And,
    CallClause,
    CallSubquery,
    Comparison,
    CreateClause,
    DeleteClause,
    MatchClause,
    MergeClause,
    Not,
    Or,
    PatternPredicate,
    Projection,
    Query,
    Ref,
    RemoveClause,
    ReturnClause,
    SetClause,
    UnwindClause,
    WithClause,
)
from gql_core.ir import (
    AggregateExpr,
    And as IRAnd,
    Arithmetic,
    Comparison as IRComparison,
    FunctionCall,
    In as IRIn,
    IsNotNull as IRIsNotNull,
    IsNull as IRIsNull,
    Literal,
    Not as IRNot,
    Or as IROr,
    Parameter,
    Property,
    RegexMatch,
    StringMatch,
    Variable,
)
from gql_core.schema import load_shapes


class SemanticError(ValueError):
    """Raised when a syntactically valid query is not valid for the KG schema."""


@dataclass
class _Binding:
    kind: str  # "node" | "edge"
    label: str | None = None


_KNOWN_FUNCTIONS = {
    "COUNT", "SUM", "AVG", "MIN", "MAX", "COLLECT",
    "SIZE", "LENGTH", "KEYS", "LABELS", "TYPE", "ID",
    "STARTNODE", "ENDNODE", "NODES", "RELATIONSHIPS", "RELS",
    "PROPERTIES", "HEAD", "LAST", "TAIL", "RANGE",
    "REVERSE", "SPLIT", "SUBSTRING", "REPLACE", "TRIM", "LTRIM", "RTRIM",
    "TOUPPER", "UPPER", "TOLOWER", "LOWER", "TOSTRING", "TO_STRING",
    "TOINTEGER", "TO_INT", "TOFLOAT", "TO_FLOAT", "TOBOOLEAN", "TO_BOOL",
    "COALESCE", "RAND", "ABS", "ROUND", "CEIL", "FLOOR", "SQRT", "SIGN",
    "E", "PI", "EXP", "LOG", "LOG10", "SIN", "COS", "TAN", "ASIN", "ACOS", "ATAN", "ATAN2",
    "COT", "DEGREES", "RADIANS", "HAVERSIN", "PROPERTY_ACCESS", "INDEX", "SLICE", "GET_PROP", "XOR", "HAS_LABEL",
    "DATE", "LOCALTIME", "TIME", "LOCALDATETIME", "DATETIME", "DURATION",
    "DATETIME.FROMEPOCH", "DATETIME.FROMEPOCHMILLIS", "LOCALDATETIME.FROMEPOCH", "LOCALDATETIME.FROMEPOCHMILLIS",
    "DURATION.BETWEEN", "DURATION.INSECONDS", "DURATION.INMONTHS", "DURATION.INDAYS",
    "DATE.TRUNCATE", "LOCALTIME.TRUNCATE", "TIME.TRUNCATE", "LOCALDATETIME.TRUNCATE", "DATETIME.TRUNCATE",
    "DATE.REALTIME", "DATE.STATEMENT", "DATE.TRANSACTION",
    "LOCALTIME.REALTIME", "LOCALTIME.STATEMENT", "LOCALTIME.TRANSACTION",
    "TIME.REALTIME", "TIME.STATEMENT", "TIME.TRANSACTION",
    "LOCALDATETIME.REALTIME", "LOCALDATETIME.STATEMENT", "LOCALDATETIME.TRANSACTION",
    "DATETIME.REALTIME", "DATETIME.STATEMENT", "DATETIME.TRANSACTION",
    "PERCENTILEDISC", "PERCENTILECONT",
    "ANY", "ALL", "NONE", "SINGLE", "LIST_COMPREHENSION", "PATTERN_COMPREHENSION", "EXISTS",
}


# Module-level default schema path. Set via set_schema_path() for
# backward-compatible usage. When None, schema-aware checks are skipped.
_default_schema_path: str | Path | None = None


def set_schema_path(path: str | Path | None) -> None:
    """Set the process-wide default schema path for validate_query.

    Call once at startup; all subsequent validate_query() calls without an
    explicit schema_path argument will use this schema.
    """
    global _default_schema_path
    _default_schema_path = path


def _resolve_schema(schema_path: str | Path | None) -> dict[str, Any] | None:
    """Resolve and load a schema, or return None if no schema is available."""
    path = schema_path or _default_schema_path
    if path is None:
        return None
    raw = load_shapes(path)

    node_props: dict[str, set[str]] = {}
    node_types: dict[str, dict[str, str]] = {}
    for label, shape in (raw.get("nodes") or {}).items():
        props = set(shape.get("required") or ()) | set(shape.get("optional") or ())
        props |= set((shape.get("types") or {}).keys())
        node_props[label] = props
        node_types[label] = dict(shape.get("types") or {})

    edge_props: dict[str, set[str]] = {}
    edge_types: dict[str, dict[str, str]] = {}
    edge_shapes: dict[str, dict[str, Any]] = {}
    for label, shape in (raw.get("edges") or {}).items():
        props = set((shape.get("properties") or {}).keys())
        edge_props[label] = props
        edge_types[label] = dict(shape.get("properties") or {})
        edge_shapes[label] = dict(shape)

    return {
        "node_props": node_props,
        "node_types": node_types,
        "edge_props": edge_props,
        "edge_types": edge_types,
        "edge_shapes": edge_shapes,
    }


def _validate_with_order_by(clause: WithClause) -> None:
    if clause.order_by is None:
        return
    if not any(p.agg is not None or _is_aggregate(p.expr) for p in clause.items):
        return
    with_allowed = set()
    projected_agg_keys = set()
    for p in clause.items:
        if p.alias:
            with_allowed.add(p.alias)
        if p.agg is None and not _is_aggregate(p.expr):
            if isinstance(p.expr, Ref):
                with_allowed.add(p.expr.var)
            elif hasattr(p.expr, "name"):
                with_allowed.add(p.expr.name)
        elif p.agg is not None:
            projected_agg_keys.add((p.agg.upper(), str(p.expr)))
        elif isinstance(p.expr, FunctionCall) and p.expr.name.upper() in ("COUNT", "SUM", "AVG", "MIN", "MAX", "COLLECT"):
            arg_str = str(p.expr.args[0]) if p.expr.args else "*"
            projected_agg_keys.add((p.expr.name.upper(), arg_str))

    for term in clause.order_by.terms:
        def _check_term(e: Any):
            if isinstance(e, Parameter):
                return
            if isinstance(e, Projection) and e.agg is not None:
                if (e.agg.upper(), str(e.expr)) in projected_agg_keys:
                    return
                raise SemanticError(f"UndefinedVariable: Cannot sort by non-projected aggregation in aggregating WITH: {e.agg}")
            if isinstance(e, FunctionCall) and e.name.upper() in ("COUNT", "SUM", "AVG", "MIN", "MAX", "COLLECT"):
                arg_str = str(e.args[0]) if e.args else "*"
                if (e.name.upper(), arg_str) in projected_agg_keys:
                    return
                raise SemanticError(f"UndefinedVariable: Cannot sort by non-projected aggregation in aggregating WITH: {e.name}")
            if isinstance(e, AggregateExpr):
                if (e.func.upper(), str(e.expr)) in projected_agg_keys:
                    return
                raise SemanticError(f"UndefinedVariable: Cannot sort by non-projected aggregation in aggregating WITH: {e.func}")
            if isinstance(e, Ref):
                if e.var.startswith("$") or e.var == "*":
                    return
                if e.var not in with_allowed:
                    raise SemanticError(f"UndefinedVariable: Variable '{e.var}' in ORDER BY is not in scope after aggregation")
            elif hasattr(e, "name") and not str(e.name).startswith("$"):
                if e.name not in with_allowed:
                    raise SemanticError(f"UndefinedVariable: Variable '{e.name}' in ORDER BY is not in scope after aggregation")
            elif hasattr(e, "args"):
                for a in e.args:
                    _check_term(a)
            elif hasattr(e, "lhs"):
                _check_term(e.lhs)
                _check_term(e.rhs)
        _check_term(term.ref)


def validate_query(
    query: Query,
    schema_path: str | Path | None = None,
    graph: Any = None,
    _outer_bindings: dict | None = None,
) -> None:
    """Validate a parsed query against the graph ontology.

    When schema_path is provided (or set via set_schema_path), full
    schema-aware checks run: known labels must use known properties, edge
    labels must exist, and endpoint labels must be compatible.

    Without a schema, only structural checks are performed (variable binding
    conflicts, unbound references). This is the generic default — the engine
    carries no embedded domain ontology.
    """
    from gql_core.query.static_types import check_static_types
    check_static_types(query)
    schema = _resolve_schema(schema_path)
    # A correlated CALL { WITH x ... } subquery sees the outer scope it imports from.
    bindings: dict[str, _Binding] = dict(_outer_bindings) if _outer_bindings else {}

    if query.clauses:
        for clause in query.clauses:
            if isinstance(clause, MatchClause):
                for pattern in clause.patterns:
                    if pattern.path_var:
                        bindings[pattern.path_var] = _Binding(kind="path")
                    for node in pattern.nodes:
                        if node.var in bindings and bindings[node.var].kind in ("edge", "path", "list"):
                            raise SyntaxError(f"TypeMismatch: Variable '{node.var}' is already bound to a {bindings[node.var].kind}, not a node")
                        _bind_node(bindings, node.var, node.label)
                        if schema is not None:
                            _validate_inline_filters(schema, bindings[node.var], node.filters, node.var)
                    for idx, rel in enumerate(pattern.rels):
                        left = pattern.nodes[idx]
                        right = pattern.nodes[idx + 1]
                        if rel.label is not None and schema is not None:
                            _validate_edge_label(schema, rel.label)
                            _validate_endpoints(schema, rel.label, rel.direction, bindings[left.var], bindings[right.var])
                        if rel.var is not None:
                            _bind_edge(bindings, rel.var, rel.label)
                if clause.where is not None:
                    if _is_aggregate(clause.where):
                        raise SyntaxError("Aggregations are not allowed in WHERE clauses")
                    w_var = None
                    if isinstance(clause.where, Ref) and clause.where.prop is None:
                        w_var = clause.where.var
                    elif isinstance(clause.where, Variable):
                        w_var = clause.where.name
                    if w_var and w_var in bindings and bindings[w_var].kind in ("node", "edge", "path"):
                        raise SyntaxError(f"TypeMismatch: expected Boolean in WHERE, got {bindings[w_var].kind}")
                    _validate_expr(schema, clause.where, bindings)

            elif isinstance(clause, CreateClause):
                for pat in clause.patterns:
                    if pat.path_var:
                        bindings[pat.path_var] = _Binding(kind="path")
                    if len(pat.nodes) == 1 and len(pat.rels) == 0:
                        if pat.nodes[0].var in bindings:
                            raise SemanticError(f"VariableAlreadyBound: Variable '{pat.nodes[0].var}' is already bound")
                    for node in pat.nodes:
                        if node.var in bindings:
                            if node.label is not None or node.filters or getattr(node, "labels", ()) or getattr(node, "has_map", False):
                                raise SemanticError(f"VariableAlreadyBound: Variable '{node.var}' is already bound and cannot have labels or properties added in CREATE")
                        for k, v in node.filters:
                            _validate_expr(schema, v, bindings)
                        if node.var and node.var not in bindings:
                            _bind_node(bindings, node.var, node.label)
                    for rel in pat.rels:
                        if rel.var and rel.var in bindings:
                            raise SemanticError(f"VariableAlreadyBound: Relationship variable '{rel.var}' is already bound")
                        if not rel.label or "|" in rel.label:
                            raise SemanticError("NoSingleRelationshipType: A single relationship type is required in CREATE")
                        if rel.direction not in ("out", "in"):
                            raise SemanticError("RequiresDirectedRelationship: Relationships in CREATE must be directed (-> or <-)")
                        if rel.quantifier != ("one",):
                            raise SemanticError("CreatingVarLength: Variable-length relationships cannot be created in CREATE")
                        for k, v in rel.filters:
                            _validate_expr(schema, v, bindings)
                        if rel.var and rel.var not in bindings:
                            _bind_edge(bindings, rel.var, rel.label)

            elif isinstance(clause, MergeClause):
                if len(clause.pattern.nodes) == 1 and len(clause.pattern.rels) == 0:
                    n0 = clause.pattern.nodes[0]
                    if n0.var and n0.var in bindings:
                        raise SyntaxError(f"Cannot merge node '{n0.var}' that is already bound")
                for r in clause.pattern.rels:
                    if r.var and r.var in bindings:
                        raise SyntaxError(f"Cannot merge relationship '{r.var}' that is already bound")
                    if not r.label:
                        raise SyntaxError("Relationship pattern in MERGE must specify a relationship type")

                if clause.pattern.rels:
                    for n in clause.pattern.nodes:
                        if n.var and n.var in bindings and (n.label is not None or n.filters or len(getattr(n, "labels", ()) or ()) > 0):
                            raise SyntaxError(f"VariableAlreadyBound: '{n.var}' cannot redeclare labels or properties in MERGE")
                for r in clause.pattern.rels:
                    if tuple(r.quantifier) != ("one",):
                        raise SyntaxError("CreatingVarLength: variable-length relationships cannot be used in MERGE")
                # Null property values in MERGE are a runtime SemanticError (see executor).

                merge_scope = dict(bindings)
                if clause.pattern.path_var:
                    bindings[clause.pattern.path_var] = _Binding(kind="path")
                    merge_scope[clause.pattern.path_var] = _Binding(kind="path")
                for node in clause.pattern.nodes:
                    if node.var not in bindings:
                        _bind_node(bindings, node.var, node.label)
                    _bind_node(merge_scope, node.var, node.label)
                for rel in clause.pattern.rels:
                    if rel.var and rel.var not in bindings:
                        _bind_edge(bindings, rel.var, rel.label)
                    _bind_edge(merge_scope, rel.var, rel.label)

                for act in clause.actions:
                    for item in act.items:
                        vname = item.target.var if isinstance(item.target, Ref) else getattr(item.target, "name", str(item.target))
                        if vname not in merge_scope and not str(vname).startswith("$"):
                            raise SyntaxError(f"UndefinedVariable: Variable '{vname}' in {act.on_event} is not defined")
                        if item.value is not None:
                            _validate_expr(schema, item.value, merge_scope)

            elif isinstance(clause, UnwindClause):
                _validate_expr(schema, clause.expr, bindings)
                bindings[clause.alias] = _Binding(kind="value")

            elif isinstance(clause, CallClause):
                if any(orig == "*" for orig, _ in clause.yield_items):
                    if len(query.clauses) > 1:
                        raise SemanticError("YIELD * is only allowed in standalone procedure calls")
                if graph is not None:
                    from gql_core.query.executor import validate_call_static
                    validate_call_static(clause, graph, len(query.clauses) == 1, set(bindings))
                for arg in clause.args:
                    _validate_expr(schema, arg, bindings)
                for orig, alias in clause.yield_items:
                    col = alias or orig
                    bindings[col] = _Binding(kind="value")

            elif isinstance(clause, CallSubquery):
                correlated = bool(clause.query.clauses) and isinstance(clause.query.clauses[0], WithClause)
                validate_query(clause.query, schema_path=schema_path, graph=graph,
                               _outer_bindings=bindings if correlated else None)
                for col, binding in _subquery_output_bindings(clause.query).items():
                    if col in bindings:
                        raise SemanticError(f"VariableAlreadyBound: Variable {col!r} returned by CALL subquery is already declared")
                    bindings[col] = binding

            elif isinstance(clause, WithClause):
                from gql_core.ir import ListExpr
                _validate_projection_aggregations(clause.items)
                for p in clause.items:
                    if p.alias is None:
                        if p.agg is not None or _is_aggregate(p.expr):
                            raise SyntaxError("Aggregations and expressions in WITH must be aliased (e.g. WITH expr AS alias)")
                        is_simple_var = (isinstance(p.expr, Ref) and p.expr.prop is None) or isinstance(p.expr, Variable) or getattr(p, "raw_expr", "") == "*"
                        if not is_simple_var:
                            raise SyntaxError(f"Expression in WITH must be aliased: {p.expr}")
                    _validate_ref(schema, p.expr, bindings, "WITH")
                _validate_skip_limit(clause.skip, "SKIP")
                _validate_skip_limit(clause.limit, "LIMIT")
                _validate_with_order_by(clause)
                has_star = any((isinstance(p.expr, Ref) and p.expr.var == "*" and p.agg is None) or getattr(p, "raw_expr", "") == "*" for p in clause.items)
                if not has_star:
                    new_bindings = {}
                    for p in clause.items:
                        orig_var = None
                        if isinstance(p.expr, Ref) and p.expr.prop is None:
                            orig_var = p.expr.var
                        elif isinstance(p.expr, Variable) and not str(p.expr.name).startswith("$"):
                            orig_var = p.expr.name

                        orig_binding = bindings.get(orig_var) if orig_var else None
                        target_key = p.alias or orig_var
                        if target_key:
                            if isinstance(p.expr, ListExpr) or p.agg == "COLLECT":
                                new_bindings[target_key] = _Binding(kind="list")
                            else:
                                new_bindings[target_key] = orig_binding if orig_binding else _Binding(kind="value")
                else:
                    new_bindings = dict(bindings)
                    for p in clause.items:
                        if p.alias:
                            if isinstance(p.expr, ListExpr) or p.agg == "COLLECT":
                                new_bindings[p.alias] = _Binding(kind="list")
                            else:
                                new_bindings[p.alias] = _Binding(kind="value")
                if clause.where is not None:
                    where_bindings = {**bindings, **new_bindings}
                    _validate_expr(schema, clause.where, where_bindings)
                bindings = new_bindings

            elif isinstance(clause, ReturnClause):
                has_star = any((isinstance(p.expr, Ref) and p.expr.var == "*" and p.agg is None) or getattr(p, "raw_expr", "") == "*" for p in clause.items)
                if has_star and all(k.startswith("__") for k in bindings):
                    raise SyntaxError("RETURN * is not allowed when there are no variables in scope")
                _validate_projection_aggregations(clause.items)
                for p in clause.items:
                    _validate_ref(schema, p.expr, bindings, "RETURN")
                _validate_skip_limit(clause.skip, "SKIP")
                _validate_skip_limit(clause.limit, "LIMIT")
                if clause.distinct and clause.order_by is not None:
                    ret_vars = set()
                    for p in clause.items:
                        if p.alias:
                            ret_vars.add(p.alias)
                        if isinstance(p.expr, Ref):
                            if p.expr.prop is None:
                                ret_vars.add(p.expr.var)
                            else:
                                ret_vars.add((p.expr.var, p.expr.prop))
                        elif isinstance(p.expr, Variable):
                            ret_vars.add(p.expr.name)
                        elif isinstance(p.expr, Property):
                            ret_vars.add((p.expr.var, p.expr.prop))
                    for term in clause.order_by.terms:
                        t = term.ref
                        t_match = False
                        if isinstance(t, Ref):
                            if (t.var, t.prop) in ret_vars or t.var in ret_vars:
                                t_match = True
                        elif hasattr(t, "name") and t.name in ret_vars:
                            t_match = True
                        if not t_match:
                            raise SyntaxError(f"When DISTINCT is used, ORDER BY can only reference expressions in RETURN: {t}")
                if clause.order_by is not None:
                    return_has_agg = any(_is_aggregate(p.expr) or p.agg is not None for p in clause.items)
                    order_has_agg = any(_is_aggregate(term.ref) for term in clause.order_by.terms)
                    if not return_has_agg and order_has_agg:
                        raise SyntaxError("Aggregation in ORDER BY is not allowed when RETURN does not aggregate")
                    aliases = {_projection_key(p) for p in clause.items}
                    alias_names = {p.alias for p in clause.items if p.alias}
                    standalone_ret_keys = set()
                    for p in clause.items:
                        if p.agg is None and not _is_aggregate(p.expr):
                            if isinstance(p.expr, Ref):
                                standalone_ret_keys.add((p.expr.var, p.expr.prop))
                            elif hasattr(p.expr, "name"):
                                standalone_ret_keys.add((p.expr.name, None))
                            if p.alias:
                                standalone_ret_keys.add((p.alias, None))

                    for term in clause.order_by.terms:
                        if isinstance(term.ref, Arithmetic) and _is_aggregate(term.ref):
                            def _check_order_agg_part(e: Any):
                                if _is_aggregate(e):
                                    return
                                if isinstance(e, Arithmetic):
                                    raise SyntaxError("Complex expressions inside ORDER BY with aggregation are not allowed")
                                if isinstance(e, Ref):
                                    if (e.var, e.prop) not in standalone_ret_keys and (e.var, None) not in standalone_ret_keys:
                                        raise SyntaxError(f"Unprojected variable '{e.var}' in ORDER BY expression containing aggregation")
                                elif hasattr(e, "name"):
                                    if (e.name, None) not in standalone_ret_keys:
                                        raise SyntaxError(f"Unprojected variable '{e.name}' in ORDER BY expression containing aggregation")
                            _check_order_agg_part(term.ref.lhs)
                            _check_order_agg_part(term.ref.rhs)
                    order_bindings = {**bindings, **{a: _Binding(kind="value") for a in alias_names if a}}
                    for term in clause.order_by.terms:
                        if isinstance(term.ref, Ref) and (term.ref.var in alias_names or term.ref.var in aliases):
                            continue
                        _validate_ref(schema, term.ref, order_bindings, "ORDER BY")

            elif isinstance(clause, SetClause):
                for item in clause.items:
                    var = item.target.var if isinstance(item.target, Ref) else getattr(item.target, "name", str(item.target))
                    if var not in bindings and not str(var).startswith("$"):
                        raise SemanticError(f"UndefinedVariable: Cannot SET on unbound variable '{var}'")
                    if item.value is not None:
                        def _has_pattern(e: Any) -> bool:
                            if isinstance(e, PatternPredicate):
                                return True
                            if hasattr(e, "args"):
                                return any(_has_pattern(a) for a in e.args)
                            if hasattr(e, "lhs") and hasattr(e, "rhs"):
                                return _has_pattern(e.lhs) or _has_pattern(e.rhs)
                            if hasattr(e, "inner"):
                                return _has_pattern(e.inner)
                            return False
                        if _has_pattern(item.value):
                            raise SyntaxError("Pattern expressions are not allowed on the right-hand side of SET")
                        _validate_expr(schema, item.value, bindings)

            elif isinstance(clause, DeleteClause):
                for item in clause.items:
                    if isinstance(item, (Arithmetic, Literal)):
                        raise SyntaxError(f"Cannot delete expression: {item}")
                    if isinstance(item, FunctionCall) and item.name in ("HAS_LABEL", "PROPERTY_ACCESS"):
                        raise SyntaxError(f"Cannot delete label or property in DELETE: {item}")
                    _validate_expr(schema, item, bindings)

            elif isinstance(clause, RemoveClause):
                for item in clause.items:
                    var = item.target.var if isinstance(item.target, Ref) else getattr(item.target, "name", str(item.target))
                    if var not in bindings and not str(var).startswith("$"):
                        raise SemanticError(f"UndefinedVariable: Cannot REMOVE on unbound variable '{var}'")

    else:
        for pattern in query.patterns:
            for node in pattern.nodes:
                _bind_node(bindings, node.var, node.label)
                if schema is not None:
                    _validate_inline_filters(schema, bindings[node.var], node.filters, node.var)

            for idx, rel in enumerate(pattern.rels):
                left = pattern.nodes[idx]
                right = pattern.nodes[idx + 1]
                if rel.label is not None and schema is not None:
                    _validate_edge_label(schema, rel.label)
                    _validate_endpoints(schema, rel.label, rel.direction, bindings[left.var], bindings[right.var])
                if rel.var is not None:
                    _bind_edge(bindings, rel.var, rel.label)

        if query.where is not None:
            _validate_expr(schema, query.where, bindings)

        if query.projections:
            _validate_projection_aggregations(query.projections)
            for projection in query.projections:
                _validate_projection(schema, projection, bindings)

        aliases = {_projection_key(p) for p in query.projections}
        alias_names = {p.alias for p in query.projections if p.alias}
        if query.order_by is not None:
            for term in query.order_by.terms:
                if isinstance(term.ref, Ref) and term.ref.var in alias_names:
                    continue
                if isinstance(term.ref, Ref) and term.ref.prop is None and term.ref.var in aliases:
                    continue
                _validate_ref(schema, term.ref, bindings, "ORDER BY")



def _is_aggregate(expr: Any) -> bool:
    from gql_core.ir import (
        AggregateExpr,
        Arithmetic,
        FunctionCall,
        StringMatch,
        RegexMatch,
        Comparison as IRComparison,
        And as IRAnd,
        Or as IROr,
        Not as IRNot,
        ListExpr,
        MapExpr,
        CaseExpr,
    )
    from gql_core.query.ast import Comparison, And, Or, Not
    if isinstance(expr, AggregateExpr):
        return True
    if isinstance(expr, Projection) and expr.agg is not None:
        return True
    if isinstance(expr, Arithmetic):
        return _is_aggregate(expr.lhs) or _is_aggregate(expr.rhs)
    if isinstance(expr, (Comparison, IRComparison)):
        return _is_aggregate(expr.lhs) or _is_aggregate(expr.rhs)
    if isinstance(expr, (And, Or, IRAnd, IROr)):
        children = expr.children if hasattr(expr, "children") else getattr(expr, "operands", ())
        return any(_is_aggregate(c) for c in children)
    if isinstance(expr, (Not, IRNot)):
        inner = expr.inner if hasattr(expr, "inner") else getattr(expr, "operand", None)
        return _is_aggregate(inner)
    if isinstance(expr, ListExpr):
        return any(_is_aggregate(e) for e in expr.elements)
    if isinstance(expr, MapExpr):
        return any(_is_aggregate(v) for _, v in expr.entries)
    if isinstance(expr, CaseExpr):
        return any(_is_aggregate(c) or _is_aggregate(r) for c, r in expr.cases) or (expr.else_expr is not None and _is_aggregate(expr.else_expr))
    if isinstance(expr, StringMatch):
        return _is_aggregate(expr.string_expr) or _is_aggregate(expr.pattern_expr)
    if isinstance(expr, RegexMatch):
        return _is_aggregate(expr.string_expr)
    if isinstance(expr, FunctionCall):
        if expr.name.upper() in ("COUNT", "SUM", "AVG", "MIN", "MAX", "COLLECT"):
            return True
        return any(_is_aggregate(a) for a in expr.args)
    return False


def _check_nested_aggregates(expr: Any, in_aggregate: bool = False, inside_name: str = "") -> None:
    from gql_core.ir import AggregateExpr, FunctionCall, Arithmetic, StringMatch, RegexMatch
    if isinstance(expr, Projection) and expr.agg is not None:
        if in_aggregate:
            raise SemanticError(f"NestedAggregation: Nested aggregation is not allowed ({expr.agg} inside {inside_name})")
        _check_nested_aggregates(expr.expr, in_aggregate=True, inside_name=expr.agg)
        return
    if isinstance(expr, AggregateExpr):
        if in_aggregate:
            raise SemanticError(f"NestedAggregation: Nested aggregation is not allowed ({expr.func} inside {inside_name})")
        _check_nested_aggregates(expr.expr, in_aggregate=True, inside_name=expr.func)
        return
    if isinstance(expr, FunctionCall):
        name_up = expr.name.upper()
        if name_up in ("COUNT", "SUM", "AVG", "MIN", "MAX", "COLLECT"):
            if in_aggregate:
                raise SemanticError(f"NestedAggregation: Nested aggregation is not allowed ({name_up} inside {inside_name})")
            for a in expr.args:
                _check_nested_aggregates(a, in_aggregate=True, inside_name=name_up)
            return
        if in_aggregate and name_up == "RAND":
            raise SemanticError("NonConstantExpression: rand() cannot be used inside an aggregate")
        for a in expr.args:
            _check_nested_aggregates(a, in_aggregate=in_aggregate, inside_name=inside_name)
        return
    if isinstance(expr, Arithmetic):
        _check_nested_aggregates(expr.lhs, in_aggregate=in_aggregate, inside_name=inside_name)
        _check_nested_aggregates(expr.rhs, in_aggregate=in_aggregate, inside_name=inside_name)
        return
    if isinstance(expr, StringMatch):
        _check_nested_aggregates(expr.string_expr, in_aggregate=in_aggregate, inside_name=inside_name)
        _check_nested_aggregates(expr.pattern_expr, in_aggregate=in_aggregate, inside_name=inside_name)
        return
    if isinstance(expr, RegexMatch):
        _check_nested_aggregates(expr.string_expr, in_aggregate=in_aggregate, inside_name=inside_name)
        return
    if isinstance(expr, (list, tuple)):
        for x in expr:
            _check_nested_aggregates(x, in_aggregate=in_aggregate, inside_name=inside_name)
        return


def _validate_projection_aggregations(projections: tuple[Projection, ...]) -> None:
    from gql_core.ir import Variable, Property, Arithmetic, FunctionCall
    standalone_keys: set[tuple[str, str | None]] = set()
    for p in projections:
        if p.agg is None and not _is_aggregate(p.expr):
            if isinstance(p.expr, Ref):
                standalone_keys.add((p.expr.var, p.expr.prop))
            elif isinstance(p.expr, Variable):
                standalone_keys.add((p.expr.name, None))
            elif isinstance(p.expr, Property):
                standalone_keys.add((p.expr.var, p.expr.prop))
            if p.alias:
                standalone_keys.add((p.alias, None))

    for p in projections:
        if isinstance(p.expr, PatternPredicate) and not p.expr.subquery:
            raise SemanticError("Pattern expressions are not allowed in projection without EXISTS")
        _check_nested_aggregates(p if p.agg is not None else p.expr)
        if p.agg is None and _is_aggregate(p.expr):
            def _check_mixed(e: Any, local_vars: set[str] | None = None):
                if local_vars is None:
                    local_vars = set()
                if _is_aggregate(e):
                    return
                if isinstance(e, FunctionCall) and e.name == "LIST_COMPREHENSION" and len(e.args) >= 4:
                    var_name = getattr(e.args[0], "name", getattr(e.args[0], "var", str(e.args[0])))
                    new_locals = local_vars | {var_name}
                    _check_mixed(e.args[1], local_vars)
                    if e.args[2] is not None:
                        _check_mixed(e.args[2], new_locals)
                    if e.args[3] is not None:
                        _check_mixed(e.args[3], new_locals)
                    return
                if isinstance(e, FunctionCall) and e.name.upper() in ("ANY", "ALL", "NONE", "SINGLE") and len(e.args) >= 2:
                    var_name = getattr(e.args[0], "name", getattr(e.args[0], "var", str(e.args[0])))
                    new_locals = local_vars | {var_name}
                    _check_mixed(e.args[1], local_vars)
                    if len(e.args) >= 3 and e.args[2] is not None:
                        _check_mixed(e.args[2], new_locals)
                    return
                if isinstance(e, Arithmetic):
                    raise SemanticError("AmbiguousAggregationExpression: Complex expression inside aggregation expression")
                if isinstance(e, (Ref, Variable, Property)):
                    vname = e.var if hasattr(e, "var") else e.name
                    pname = getattr(e, "prop", None)
                    if str(vname).startswith("$") or vname in local_vars:
                        return
                    if (vname, pname) not in standalone_keys and (vname, None) not in standalone_keys:
                        raise SemanticError(f"AmbiguousAggregationExpression: Variable '{vname}' inside aggregation is not grouped")
                if isinstance(e, FunctionCall):
                    for a in e.args:
                        _check_mixed(a, local_vars)

            if isinstance(p.expr, FunctionCall) and p.expr.name.upper() not in ("COUNT", "SUM", "AVG", "MIN", "MAX", "COLLECT"):
                _check_mixed(p.expr)
            elif isinstance(p.expr, Arithmetic):
                _check_mixed(p.expr.lhs)
                _check_mixed(p.expr.rhs)
            elif isinstance(p.expr, StringMatch):
                _check_mixed(p.expr.string_expr)
                _check_mixed(p.expr.pattern_expr)
            elif isinstance(p.expr, RegexMatch):
                _check_mixed(p.expr.string_expr)



def _subquery_output_bindings(query: Query) -> dict[str, _Binding]:
    """Columns a CALL { ... } subquery adds to the outer scope (from its final RETURN).

    A bare variable keeps its node/edge kind and label so the outer query can
    read its properties; anything else is a plain value.
    """
    ret = next((cl for cl in reversed(query.clauses) if isinstance(cl, ReturnClause)), None)
    if ret is None:
        return {}
    kinds: dict[str, _Binding] = {}
    for cl in query.clauses:
        if isinstance(cl, MatchClause):
            for pat in cl.patterns:
                for node in pat.nodes:
                    if node.var:
                        kinds.setdefault(node.var, _Binding(kind="node", label=node.label))
                for rel in pat.rels:
                    if rel.var:
                        kinds.setdefault(rel.var, _Binding(kind="edge", label=rel.label))
    out: dict[str, _Binding] = {}
    for p in ret.items:
        var = _bare_var_name(p.expr)
        col = p.alias or var
        if col is None:
            continue
        out[col] = kinds.get(var, _Binding(kind="value")) if var else _Binding(kind="value")
    return out


def _bare_var_name(expr: Any) -> str | None:
    if isinstance(expr, Ref) and expr.prop is None:
        return expr.var
    if isinstance(expr, Variable):
        return expr.name
    return None

def _bind_node(bindings: dict[str, _Binding], var: str, label: str | None) -> None:
    existing = bindings.get(var)
    if existing is None:
        bindings[var] = _Binding(kind="node", label=label)
        return
    if existing.kind == "edge":
        raise SemanticError(f"VariableTypeConflict: Variable {var!r} is already bound as an edge")
    if existing.kind == "path":
        raise SemanticError(f"VariableTypeConflict: Variable {var!r} is already bound as a path")
    if label is not None:
        existing.label = label
    existing.kind = "node"


def _bind_edge(bindings: dict[str, _Binding], var: str, label: str | None) -> None:
    existing = bindings.get(var)
    if existing is None:
        bindings[var] = _Binding(kind="edge", label=label)
        return
    if existing.kind == "node":
        raise SemanticError(f"VariableTypeConflict: Variable {var!r} is already bound as a node")
    if existing.kind == "path":
        raise SemanticError(f"VariableTypeConflict: Variable {var!r} is already bound as a path")
    if label is not None:
        existing.label = label
    existing.kind = "edge"


def _validate_inline_filters(
    schema: dict,
    binding: _Binding,
    filters: tuple[tuple[str, Any], ...],
    var: str,
) -> None:
    for prop, _value in filters:
        _validate_property(schema, binding, prop, f"inline filter on {var!r}")


def _validate_skip_limit(val: Any, name: str) -> None:
    if val is None:
        return
    from gql_core.ir import Literal, Parameter, Variable, Property, Arithmetic
    if isinstance(val, (Ref, Variable, Property)):
        raise SemanticError(f"NonConstantExpression: {name} expressions cannot depend on variables")
    if isinstance(val, Parameter):
        return
    def _has_var(e: Any) -> bool:
        if isinstance(e, (Ref, Variable, Property)):
            return True
        if isinstance(e, Arithmetic):
            return _has_var(e.lhs) or _has_var(e.rhs)
        if isinstance(e, StringMatch):
            return _has_var(e.string_expr) or _has_var(e.pattern_expr)
        if isinstance(e, RegexMatch):
            return _has_var(e.string_expr)
        return False
    if _has_var(val):
        raise SemanticError(f"NonConstantExpression: {name} expressions cannot depend on variables")
    try:
        from gql_core.physical.evaluator import eval_value
        res = eval_value(val, {})
        if isinstance(res, float) and not res.is_integer():
            raise SemanticError(f"InvalidArgumentType: {name} must be an integer, got float {res}")
        if isinstance(res, (int, float)):
            if res < 0:
                raise SemanticError(f"InvalidArguments: {name} must be non-negative, got {res}")
    except SemanticError:
        raise
    except Exception:
        pass


def _validate_expr(schema: dict | None, expr: Any, bindings: dict[str, _Binding]) -> None:
    if expr is None:
        return
    if isinstance(expr, (int, float, str, bool, Literal, Parameter)):
        return
    if isinstance(expr, Ref):
        _validate_ref(schema, expr, bindings, "WHERE")
        return
    if isinstance(expr, Variable):
        if expr.name.startswith("$") or expr.name == "*":
            return
        if expr.name not in bindings:
            raise SemanticError(f"UndefinedVariable: WHERE references unbound variable {expr.name!r}")
        return
    if isinstance(expr, Property):
        if expr.var not in bindings and not expr.var.startswith("$"):
            raise SemanticError(f"UndefinedVariable: WHERE references unbound variable {expr.var!r}")
        if bindings.get(expr.var) and bindings[expr.var].kind == "path":
            raise SyntaxError(f"Cannot access property on a path: {expr.var}.{expr.prop}")
        if schema is not None and expr.var in bindings:
            _validate_property(schema, bindings[expr.var], expr.prop, f"WHERE reference {expr.var}.{expr.prop}")
        return
    from gql_core.ir import MapExpr
    if isinstance(expr, MapExpr):
        for _, v in expr.entries:
            _validate_expr(schema, v, bindings)
        return
    if isinstance(expr, (Comparison, IRComparison)):
        _validate_expr(schema, expr.lhs, bindings)
        _validate_expr(schema, expr.rhs, bindings)
        return
    if isinstance(expr, (And, Or, IRAnd, IROr)):
        for child in expr.children:
            _validate_expr(schema, child, bindings)
        return
    if isinstance(expr, (Not, IRNot)):
        _validate_expr(schema, expr.inner, bindings)
        return
    if isinstance(expr, StringMatch):
        _validate_expr(schema, expr.string_expr, bindings)
        _validate_expr(schema, expr.pattern_expr, bindings)
        return
    if isinstance(expr, RegexMatch):
        _validate_expr(schema, expr.string_expr, bindings)
        return
    if isinstance(expr, IRIn):
        elem = getattr(expr, "element", getattr(expr, "lhs", None))
        coll = getattr(expr, "collection", getattr(expr, "rhs", None))
        _validate_expr(schema, elem, bindings)
        _validate_expr(schema, coll, bindings)
        return
    if isinstance(expr, (IRIsNull, IRIsNotNull)):
        _validate_expr(schema, expr.expr, bindings)
        return
    if isinstance(expr, Arithmetic):
        _validate_expr(schema, expr.lhs, bindings)
        _validate_expr(schema, expr.rhs, bindings)
        return
    if isinstance(expr, FunctionCall):
        fname_upper = expr.name.upper()
        if fname_upper not in _KNOWN_FUNCTIONS and not fname_upper.startswith("__"):
            raise SyntaxError(f"UnknownFunction: Unknown function {expr.name!r}")
        if fname_upper == "TYPE" and expr.args:
            arg0 = expr.args[0]
            var_name = getattr(arg0, "var", getattr(arg0, "name", None))
            if var_name and var_name in bindings and bindings[var_name].kind == "node":
                raise SyntaxError(f"TypeMismatch: type() takes a relationship, got node '{var_name}'")
        if fname_upper == "LENGTH" and expr.args:
            arg0 = expr.args[0]
            var_name = getattr(arg0, "var", getattr(arg0, "name", None))
            if var_name and var_name in bindings and bindings[var_name].kind in ("node", "edge"):
                raise SyntaxError(f"TypeMismatch: length() takes a path or string, got {bindings[var_name].kind} '{var_name}'")
        if fname_upper == "SIZE" and expr.args:
            arg0 = expr.args[0]
            var_name = getattr(arg0, "var", getattr(arg0, "name", None))
            if var_name and var_name in bindings and bindings[var_name].kind == "path":
                raise SyntaxError(f"TypeMismatch: size() cannot be applied to a path '{var_name}', use length() instead")
        if expr.name == "PROPERTY_ACCESS" and len(expr.args) >= 1:
            _validate_expr(schema, expr.args[0], bindings)
            return
        if expr.name == "LIST_COMPREHENSION" and len(expr.args) >= 4:
            var_item = expr.args[0]
            coll_expr = expr.args[1]
            where_cond = expr.args[2]
            map_expr = expr.args[3]
            if map_expr is not None and _is_aggregate(map_expr):
                raise SyntaxError("Aggregations are not allowed in list comprehension mapping expression")
            _validate_expr(schema, coll_expr, bindings)
            var_name = getattr(var_item, "name", str(var_item))
            inner_bindings = dict(bindings)
            inner_bindings[var_name] = _Binding(kind="value")
            if where_cond is not None:
                _validate_expr(schema, where_cond, inner_bindings)
            if map_expr is not None:
                _validate_expr(schema, map_expr, inner_bindings)
            return
        if expr.name == "PATTERN_COMPREHENSION" and len(expr.args) >= 1:
            pat = expr.args[0]
            where_cond = expr.args[1] if len(expr.args) == 3 and expr.args[1] is not None else None
            map_expr = expr.args[-1] if len(expr.args) > 1 else None
            inner_bindings = dict(bindings)
            if hasattr(pat, "nodes"):
                for n in pat.nodes:
                    if getattr(n, "var", None):
                        inner_bindings[n.var] = _Binding(kind="node", label=getattr(n, "label", None))
            if hasattr(pat, "rels"):
                for r in pat.rels:
                    if getattr(r, "var", None):
                        inner_bindings[r.var] = _Binding(kind="edge", label=getattr(r, "label", None))
            if hasattr(pat, "path_var") and pat.path_var:
                inner_bindings[pat.path_var] = _Binding(kind="path")
            if where_cond is not None:
                _validate_expr(schema, where_cond, inner_bindings)
            if map_expr is not None:
                _validate_expr(schema, map_expr, inner_bindings)
            return
        if expr.name.upper() in ("ANY", "ALL", "NONE", "SINGLE") and len(expr.args) >= 2:
            var_item = expr.args[0]
            coll_expr = expr.args[1]
            _validate_expr(schema, coll_expr, bindings)
            var_name = getattr(var_item, "name", getattr(var_item, "var", str(var_item)))
            inner_bindings = dict(bindings)
            inner_bindings[var_name] = _Binding(kind="value")
            if len(expr.args) >= 3 and expr.args[2] is not None:
                _validate_expr(schema, expr.args[2], inner_bindings)
            return
        for a in expr.args:
            _validate_expr(schema, a, bindings)
        return
    if isinstance(expr, AggregateExpr):
        _validate_expr(schema, expr.expr, bindings)
        return
    if isinstance(expr, PatternPredicate):
        return
    if isinstance(expr, (list, tuple)):
        for it in expr:
            _validate_expr(schema, it, bindings)
        return
    if isinstance(expr, dict):
        for v in expr.values():
            _validate_expr(schema, v, bindings)
        return
    if hasattr(expr, "lhs") and hasattr(expr, "rhs"):
        _validate_expr(schema, expr.lhs, bindings)
        _validate_expr(schema, expr.rhs, bindings)
        return
    if hasattr(expr, "inner"):
        _validate_expr(schema, expr.inner, bindings)
        return
    if hasattr(expr, "children"):
        for child in expr.children:
            _validate_expr(schema, child, bindings)
        return


def _validate_projection(schema: dict | None, projection: Projection, bindings: dict[str, _Binding]) -> None:
    _validate_ref(schema, projection.expr, bindings, "RETURN")
    if schema is None:
        return
    if projection.agg in {"SUM", "AVG"}:
        if isinstance(projection.expr, Ref) and projection.expr.prop is not None:
            if projection.expr.var in bindings:
                type_name = _property_type(schema, bindings[projection.expr.var], projection.expr.prop)
                if type_name not in {None, "int", "float"}:
                    raise SemanticError(
                        f"{projection.agg} cannot be applied to non-numeric property "
                        f"{projection.expr.var}.{projection.expr.prop}"
                    )


def _validate_ref(schema: dict | None, ref: Any, bindings: dict[str, _Binding], context: str) -> None:
    if ref is None:
        return
    if isinstance(ref, (int, float, str, bool, Literal, Parameter)):
        return
    if isinstance(ref, Variable):
        if ref.name.startswith("$") or ref.name == "*":
            return
        if ref.name not in bindings:
            raise SemanticError(f"UndefinedVariable: {context} references unbound variable {ref.name!r}")
        return
    if isinstance(ref, Property):
        if ref.var not in bindings and not ref.var.startswith("$"):
            raise SemanticError(f"UndefinedVariable: {context} references unbound variable {ref.var!r}")
        if bindings.get(ref.var) and bindings[ref.var].kind == "path":
            raise SyntaxError(f"Cannot access property on a path: {ref.var}.{ref.prop}")
        if schema is not None and ref.var in bindings:
            _validate_property(schema, bindings[ref.var], ref.prop, f"{context} reference {ref.var}.{ref.prop}")
        return
    if not isinstance(ref, Ref):
        _validate_expr(schema, ref, bindings)
        return
    if ref.var == "*" or ref.var.startswith("$"):
        return
    binding = bindings.get(ref.var)
    if binding is None:
        raise SemanticError(f"{context} references unbound variable {ref.var!r}")
    if binding.kind == "path" and ref.prop is not None:
        raise SyntaxError(f"Cannot access property on a path: {ref.var}.{ref.prop}")
    if ref.prop is not None and schema is not None:
        _validate_property(schema, binding, ref.prop, f"{context} reference {ref.var}.{ref.prop}")


def _validate_property(schema: dict, binding: _Binding, prop: str, context: str) -> None:
    if binding.label is None:
        return
    if binding.kind == "node":
        props = schema["node_props"].get(binding.label)
    else:
        props = schema["edge_props"].get(binding.label)
    if props is None:
        return
    if prop not in props:
        raise SemanticError(
            f"{context} uses unknown {binding.kind} property {prop!r} on label {binding.label!r}"
        )


def _property_type(schema: dict, binding: _Binding, prop: str) -> str | None:
    if binding.label is None:
        return None
    if binding.kind == "node":
        return schema["node_types"].get(binding.label, {}).get(prop)
    return schema["edge_types"].get(binding.label, {}).get(prop)


def _validate_edge_label(schema: dict, label: str) -> None:
    if label not in schema["edge_shapes"]:
        raise SemanticError(f"Unknown edge label {label!r}")


def _validate_endpoints(
    schema: dict,
    label: str,
    direction: str,
    left: _Binding,
    right: _Binding,
) -> None:
    shape = schema["edge_shapes"][label]
    src = shape.get("src")
    dst = shape.get("dst")
    if not src or not dst or left.label is None or right.label is None:
        return

    if direction == "out":
        expected = (src, dst)
    elif direction == "in":
        expected = (dst, src)
    else:
        if (left.label, right.label) in {(src, dst), (dst, src)}:
            return
        expected = (src, dst)

    if (left.label, right.label) != expected:
        raise SemanticError(
            f"Edge {label!r} with direction {direction!r} expects endpoints "
            f"{expected[0]} -> {expected[1]}, got {left.label} -> {right.label}"
        )


def _projection_key(projection: Projection) -> str:
    if projection.alias is not None:
        return projection.alias
    if projection.raw_expr:
        return projection.raw_expr
    if projection.agg is not None:
        var = projection.expr.var if isinstance(projection.expr, Ref) else str(projection.expr)
        prop = projection.expr.prop if isinstance(projection.expr, Ref) else ""
        return f"{projection.agg.lower()}_{var}" + (
            f"_{prop}" if prop else ""
        )
    if isinstance(projection.expr, Ref):
        return projection.expr.prop or projection.expr.var
    return str(projection.expr)
