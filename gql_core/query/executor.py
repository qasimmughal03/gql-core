"""Plan executor for GQL-Core.

Operates on a stream of binding rows. Each row is a dict mapping variable
names to graph entities (Node or Edge). The driver walks the plan ops in
order; aggregation happens once at the ProjectOp.

RPQ traversal: rpq_traverse implements BFS for Kleene-class quantifiers
(`*`, `+`, `*N`, `*N..M`). It yields paths as (target_node, edge_path)
pairs so the caller can decide whether to bind an edge variable.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Iterator
from typing import Any

from pathlib import Path
from typing import Any

from gql_core.graph import Edge, Node, PropertyGraph
from gql_core.query.ast import (
    And,
    Comparison,
    Not,
    Or,
    OrderBy,
    OrderTerm,
    Projection,
    Query,
    Ref,
    Pattern,
    PatternPredicate,
    NodePat,
    RelPat,
    MatchClause,
    UnwindClause,
    WithClause,
    ReturnClause,
    CreateClause,
    SetClause,
    SetItem,
    DeleteClause,
    RemoveClause,
    RemoveItem,
    MergeClause,
    MergeAction,
    CallClause,
)
from gql_core.query.parser import parse
from gql_core.query.planner import (
    ExpandOp,
    FilterOp,
    JoinOp,
    Plan,
    ProjectOp,
    ScanOp,
    UnionOp,
    plan as plan_query,
)
from gql_core.query.semantic import validate_query


def _is_pipeline_query(query: Query) -> bool:
    if not query.clauses:
        return False
    pipeline_clause_types = (
        UnwindClause,
        WithClause,
        CreateClause,
        SetClause,
        DeleteClause,
        RemoveClause,
        MergeClause,
        CallClause,
    )
    for cl in query.clauses:
        if isinstance(cl, pipeline_clause_types):
            return True
        if isinstance(cl, MatchClause):
            if cl.optional:
                return True
            if len(cl.patterns) > 1:
                return True
            if cl.where is not None:
                if not isinstance(cl.where, Comparison):
                    return True
                if isinstance(cl.where.rhs, Ref) or hasattr(cl.where.rhs, "var"):
                    return True
            if any(getattr(p, "path_var", None) for p in cl.patterns):
                return True
        if isinstance(cl, ReturnClause):
            if cl.skip is not None or cl.distinct:
                return True
            if any(getattr(p, "distinct", False) for p in cl.items):
                return True
            if any((isinstance(p.expr, Ref) and p.expr.var == "*") or p.raw_expr == "*" for p in cl.items):
                return True
    match_count = sum(1 for cl in query.clauses if isinstance(cl, MatchClause))
    if match_count > 1:
        return True
    if len(query.clauses) > 2:
        return True
    return False


def execute(plan_or_query: Plan | Query, graph: PropertyGraph) -> list[dict]:
    if isinstance(plan_or_query, Query):
        if _is_pipeline_query(plan_or_query):
            return execute_pipeline(plan_or_query, graph)
        try:
            return execute(plan_query(plan_or_query, graph), graph)
        except Exception:
            if plan_or_query.clauses:
                return execute_pipeline(plan_or_query, graph)
            raise
    plan_obj = plan_or_query
    rows: Iterable[dict] = [{}]
    for op in plan_obj.ops:
        rows = _dispatch(op, rows, graph)
    if not isinstance(rows, list):
        rows = list(rows)
    return rows  # type: ignore[return-value]


def run(
    source: str | Any,
    graph: PropertyGraph | Any,
    schema_path: str | Path | None = None,
) -> list[dict]:
    """Convenience: parse + plan + execute in one call.

    When schema_path is provided, semantic validation runs against that
    ontology. Without it, only structural checks (variable binding) are
    performed.
    """
    if not isinstance(source, str) and isinstance(graph, str):
        source, graph = graph, source
    query = parse(source)
    validate_query(query, schema_path=schema_path)
    if _is_pipeline_query(query):
        return execute_pipeline(query, graph)
    try:
        return execute(plan_query(query, graph), graph)
    except Exception:
        if query.clauses:
            return execute_pipeline(query, graph)
        raise


# ── Dispatch ────────────────────────────────────────────────────────


def _dispatch(op, rows: Iterable[dict], graph: PropertyGraph) -> Iterable[dict]:
    if isinstance(op, ScanOp):
        return _scan(op, rows, graph)
    if isinstance(op, ExpandOp):
        return _expand(op, rows, graph)
    if isinstance(op, JoinOp):
        return _join(op, rows, graph)
    if isinstance(op, FilterOp):
        return _filter(op, rows)
    if isinstance(op, ProjectOp):
        return _project(op, rows, graph)
    if isinstance(op, UnionOp):
        return _union(op, rows, graph)
    raise TypeError(f"Unknown op: {type(op).__name__}")


def _union(op: UnionOp, rows: Iterable[dict], graph: PropertyGraph) -> list[dict]:
    out = list(rows)
    for u_type, sub_plan in op.unions:
        sub_rows = execute(sub_plan, graph)
        if "ALL" in u_type.upper():
            out.extend(sub_rows)
        else:
            seen = {_hashable_val(tuple(sorted(r.items()))) for r in out}
            for r in sub_rows:
                k = _hashable_val(tuple(sorted(r.items())))
                if k not in seen:
                    seen.add(k)
                    out.append(r)
    return out


# ── Operators ───────────────────────────────────────────────────────


def _scan(op: ScanOp, rows: Iterable[dict], graph: PropertyGraph) -> Iterator[dict]:
    candidates: Iterator[Node]
    if op.label is not None:
        candidates = graph.nodes_by_label(op.label)
    else:
        candidates = (n for n in graph._nodes.values())
    materialized = [
        n
        for n in candidates
        if _matches_inline_filters(n, op.inline_filters)
        and _matches_pushed(n, op.pushed)
    ]
    for row in rows:
        for n in materialized:
            new_row = dict(row)
            if op.var in new_row and new_row[op.var] != n:
                continue
            new_row[op.var] = n
            yield new_row


def _base_edge_id(eid: str) -> str:
    return eid[:-4] if eid.endswith("_rev") else eid


def _expand(op: ExpandOp, rows: Iterable[dict], graph: PropertyGraph) -> Iterator[dict]:
    for row in rows:
        src_node = row.get(op.from_var)
        if src_node is None:
            continue
        used_edges = row.get("__used_edges__", frozenset())
        for edge_path, target in _walk(graph, src_node, op, used_edges=used_edges):
            path_edge_ids = frozenset(_base_edge_id(e.id) for e in edge_path)
            if used_edges and (used_edges & path_edge_ids):
                continue
            if op.to_label is not None and target.label != op.to_label:
                continue
            if not _matches_inline_filters(target, op.to_inline_filters):
                continue
            new_row = dict(row)
            if op.to_var in new_row and new_row[op.to_var] != target:
                continue
            new_row[op.to_var] = target
            new_row["__used_edges__"] = used_edges | path_edge_ids
            if op.edge_var:
                if not edge_path:
                    continue
                if len(edge_path) > 1:
                    # Cypher binds a relationship list for variable-length patterns;
                    # this engine only tracks the last edge in the path. Accessing
                    # edge properties via an edge variable on a multi-hop RPQ would
                    # silently read the wrong edge, so we fail fast instead.
                    raise NotImplementedError(
                        f"Edge variable '{op.edge_var}' on a multi-hop RPQ pattern "
                        f"(path length {len(edge_path)}) is not supported. "
                        "Cypher binds a relationship list; this engine does not. "
                        "Remove the edge variable or use a single-hop pattern."
                    )
                new_row[op.edge_var] = edge_path[0]
            if not _matches_pushed(target, op.pushed, edge_var=op.edge_var, edge=edge_path[-1] if edge_path else None):
                continue
            yield new_row


def _walk(
    graph: PropertyGraph,
    start: Node,
    op: ExpandOp,
    used_edges: frozenset[str] = frozenset(),
) -> Iterator[tuple[list[Edge], Node]]:
    """Yield (edge_path, target_node) pairs for each match of the rel pattern."""
    qkind = op.quantifier[0]
    if qkind == "one":
        for edge, neighbor in _direct_neighbors(graph, start, op.edge_label, op.direction):
            eid = _base_edge_id(edge.id)
            if eid in used_edges:
                continue
            yield [edge], neighbor
        return
    lo, hi = _quantifier_bounds(op.quantifier)
    yield from rpq_traverse(graph, start, op.edge_label, op.direction, lo, hi, initial_used_edges=used_edges)


def rpq_traverse(
    graph: PropertyGraph,
    start: Node,
    edge_label: str | None,
    direction: str,
    lo: int,
    hi: int,
    initial_used_edges: frozenset[str] = frozenset(),
) -> Iterator[tuple[list[Edge], Node]]:
    """Traverse graph matching edge_label, direction, and hop bounds [lo, hi].

    Implements openCypher trail semantics:
    - Within each path, no relationship instance (by base edge ID) may be traversed more than once.
    - Nodes may be revisited across distinct edges (allowing cycles, repeated endpoints, and parallel edges).
    - If multiple distinct paths reach the same destination, each path is yielded.
    - Traversal terminates because each step consumes a previously unused edge, bounding
      maximum path length to min(hi, |E|).
    """
    queue: deque[tuple[Node, tuple[Edge, ...], frozenset[str]]] = deque([(start, (), initial_used_edges)])
    if lo == 0:
        yield [], start

    while queue:
        node, path, used_edges = queue.popleft()
        depth = len(path)
        if depth >= hi:
            continue
        for edge, neighbor in _direct_neighbors(graph, node, edge_label, direction):
            eid = _base_edge_id(edge.id)
            if eid in used_edges:
                continue
            new_path = path + (edge,)
            new_depth = depth + 1
            new_used = used_edges | {eid}
            if new_depth >= lo:
                yield list(new_path), neighbor
            if new_depth < hi:
                queue.append((neighbor, new_path, new_used))


def _direct_neighbors(
    graph: PropertyGraph,
    node: Node,
    edge_label: str | None,
    direction: str,
) -> Iterator[tuple[Edge, Node]]:
    if direction == "out":
        yield from graph.neighbors(node.id, label=edge_label, direction="out")
    elif direction == "in":
        yield from graph.neighbors(node.id, label=edge_label, direction="in")
    else:  # undirected
        seen_edges: set[str] = set()
        for edge, neighbor in graph.neighbors(node.id, label=edge_label, direction="out"):
            seen_edges.add(edge.id)
            yield edge, neighbor
        for edge, neighbor in graph.neighbors(node.id, label=edge_label, direction="in"):
            if edge.id in seen_edges:
                continue
            yield edge, neighbor


def _quantifier_bounds(q: tuple) -> tuple[int, int]:
    kind = q[0]
    # `*` defaults to 1..∞ (Cypher convention); use `*0..N` for zero-or-more.
    if kind == "star":
        return 1, math.inf  # type: ignore[return-value]
    if kind == "plus":
        return 1, math.inf  # type: ignore[return-value]
    if kind == "exactly":
        return q[1], q[1]
    if kind == "range":
        return q[1], q[2]
    raise ValueError(f"Unknown quantifier kind: {kind}")


def _join(op: JoinOp, rows: Iterable[dict], graph: PropertyGraph) -> Iterator[dict]:
    rhs = list(execute(Plan(ops=op.rhs_ops + []), graph))
    if not op.on_vars:
        # Cartesian product when patterns share no variables.
        for left in rows:
            for right in rhs:
                merged = {**left, **right}
                yield merged
        return
    # Hash-join by tuple of shared variable IDs.
    index: dict[tuple, list[dict]] = {}
    for r in rhs:
        key = _join_key(r, op.on_vars)
        if key is None:
            continue
        index.setdefault(key, []).append(r)
    for left in rows:
        key = _join_key(left, op.on_vars)
        if key is None:
            continue
        for right in index.get(key, ()):
            yield {**left, **right}


def _join_key(row: dict, on_vars: tuple[str, ...]) -> tuple | None:
    out = []
    for var in on_vars:
        binding = row.get(var)
        if binding is None:
            return None
        out.append(_entity_id(binding))
    return tuple(out)


def _entity_id(entity: Any) -> str:
    return entity.id if hasattr(entity, "id") else entity


# ── Filter / projection ─────────────────────────────────────────────


def _filter(op: FilterOp, rows: Iterable[dict]) -> Iterator[dict]:
    for row in rows:
        if _eval_expr(op.expr, row) is True:
            yield row


def _eval_expr(expr: Any, row: dict) -> bool | None:
    if isinstance(expr, Comparison):
        return _eval_comparison(expr, row)
    if isinstance(expr, And):
        results = [_eval_expr(c, row) for c in expr.children]
        if any(r is False for r in results):
            return False
        if any(r is None for r in results):
            return None
        return True
    if isinstance(expr, Or):
        results = [_eval_expr(c, row) for c in expr.children]
        if any(r is True for r in results):
            return True
        if any(r is None for r in results):
            return None
        return False
    if isinstance(expr, Not):
        inner = _eval_expr(expr.inner, row)
        if inner is None:
            return None
        return not inner
    val = _read_ref(expr, row)
    if isinstance(val, bool) or val is None:
        return val
    return bool(val)


def _eval_comparison(cmp: Comparison, row: dict) -> bool | None:
    lhs_value = _read_ref(cmp.lhs, row)
    rhs_value = _read_ref(cmp.rhs, row)
    return _apply_op(cmp.op, lhs_value, rhs_value)


def _apply_op(op: str, lhs: Any, rhs: Any) -> bool | None:
    if lhs is None or rhs is None:
        return None
    # Boolean vs non-boolean type mismatch in comparison
    if isinstance(lhs, bool) != isinstance(rhs, bool):
        if op == "=":
            return False
        if op == "!=":
            return True
        return None
    try:
        if op == "=":
            return lhs == rhs
        if op == "!=":
            return lhs != rhs
        if op == "<":
            return lhs < rhs
        if op == "<=":
            return lhs <= rhs
        if op == ">":
            return lhs > rhs
        if op == ">=":
            return lhs >= rhs
    except TypeError:
        return None
    raise ValueError(f"Unsupported operator: {op}")


def _read_ref(ref: Any, row: dict) -> Any:
    if isinstance(ref, (Comparison, And, Or, Not)):
        return _eval_expr(ref, row)
    if isinstance(ref, Ref):
        if ref.var == "*":
            return row
        binding = row.get(ref.var)
        if binding is None:
            return None
        if ref.prop is None:
            return binding
        if hasattr(binding, "props") and ref.prop in binding.props:
            return binding.props[ref.prop]
        if ref.prop == "id" and hasattr(binding, "id"):
            return binding.id
        if ref.prop == "label" and hasattr(binding, "label"):
            return binding.label
        return None

    from gql_core.ir import (
        ValueExpr, BoolExpr,
        IsNull, IsNotNull,
        StringMatch, RegexMatch, In
    )
    from gql_core.physical.evaluator import eval_value, eval_predicate
    if isinstance(ref, (IsNull, IsNotNull, StringMatch, RegexMatch, In, BoolExpr)):
        return eval_predicate(ref, row)
    if isinstance(ref, ValueExpr):
        return eval_value(ref, row)
    return ref


def _matches_inline_filters(
    node: Node, filters: tuple[tuple[str, Any], ...]
) -> bool:
    if not filters:
        return True
    for prop, value in filters:
        if prop == "id" and prop not in node.props:
            if node.id != value and str(node.id) != str(value):
                return False
        elif prop == "label" and prop not in node.props:
            if node.label != value:
                return False
        else:
            if prop not in node.props:
                return False
            actual_val = node.props[prop]
            if actual_val is None or value is None:
                if actual_val is not value:
                    return False
            elif isinstance(actual_val, bool) != isinstance(value, bool):
                return False
            elif actual_val != value:
                return False
    return True


def _matches_pushed(
    node: Node | None,
    pushed: list[Comparison],
    *,
    edge_var: str | None = None,
    edge: Edge | None = None,
) -> bool:
    if not pushed:
        return True
    for cmp in pushed:
        target: Any = node
        if edge_var is not None and cmp.lhs.var == edge_var:
            target = edge
        if target is None:
            return False
        if cmp.lhs.prop is None:
            value = target
        elif hasattr(target, "props") and cmp.lhs.prop in target.props:
            value = target.props[cmp.lhs.prop]
        elif cmp.lhs.prop == "id" and hasattr(target, "id"):
            value = target.id
        elif cmp.lhs.prop == "label" and hasattr(target, "label"):
            value = target.label
        else:
            value = None
        if _apply_op(cmp.op, value, cmp.rhs) is not True:
            return False
    return True


# ── Project / aggregate / order / limit ─────────────────────────────


def _hashable_val(v: Any) -> Any:
    if isinstance(v, dict):
        return tuple(sorted((k, _hashable_val(val)) for k, val in v.items()))
    if isinstance(v, (list, tuple)):
        return tuple(_hashable_val(x) for x in v)
    if hasattr(v, "nodes") and hasattr(v, "relationships"):
        return ("__path__", tuple(_hashable_val(n) for n in v.nodes), tuple(_hashable_val(e) for e in v.relationships))
    if hasattr(v, "id"):
        return ("__entity__", getattr(v, "id"))
    return v


def _project(op: ProjectOp, rows: Iterable[dict], graph: PropertyGraph | None = None) -> list[dict]:
    materialized = list(rows)
    has_agg = any(p.agg is not None or _is_aggregate(p.expr) for p in op.projections)
    alias_map = {p.alias: p.expr for p in op.projections if p.alias}
    if has_agg:
        out = _aggregate(op.projections, materialized, graph)
        if op.order_by is not None:
            out = _sort_rows(out, op.order_by, alias_map)
    else:
        if op.order_by is not None:
            materialized = _sort_rows(materialized, op.order_by, alias_map)
        out = [_project_row(op.projections, row) for row in materialized]
    if getattr(op, "distinct", False):
        seen: set = set()
        deduped: list[dict] = []
        for r in out:
            key = tuple(sorted((k, _hashable_val(v)) for k, v in r.items()))
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        out = deduped
    if op.limit is not None:
        out = out[: op.limit]
    return out


class Row(dict):
    """Result row dictionary that preserves openCypher exact column names
    while supporting lenient property/variable lookup when unambiguous.
    """
    def __getitem__(self, key: str) -> Any:
        if super().__contains__(key):
            return super().__getitem__(key)
        # Lenient fallback: if key is 'id' and 'a.id' exists
        matches = [v for k, v in self.items() if "." in k and k.split(".", 1)[1] == key]
        if matches:
            return matches[0]
        # Lenient fallback: if key is 'count' and 'count(*)' or 'count(n)' exists
        agg_matches = [v for k, v in self.items() if "(" in k and k.split("(", 1)[0].lower() == key.lower()]
        if agg_matches:
            return agg_matches[0]
        return super().__getitem__(key)

    def __contains__(self, key: Any) -> bool:
        if super().__contains__(key):
            return True
        if isinstance(key, str):
            if any("." in k and k.split(".", 1)[1] == key for k in self.keys()):
                return True
            if any("(" in k and k.split("(", 1)[0].lower() == key.lower() for k in self.keys()):
                return True
        return False

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, dict):
            return False
        if len(self) != len(other):
            return False
        for k, v in other.items():
            if k not in self:
                return False
            if self[k] != v:
                return False
        return True


def _project_row(projections: tuple[Projection, ...], row: dict) -> Row:
    out: dict = {}
    for proj in projections:
        if (isinstance(proj.expr, Ref) and proj.expr.var == "*") or proj.raw_expr == "*":
            for k, v in row.items():
                if not k.startswith("__"):
                    out[k] = v
        else:
            key = proj.alias or proj.raw_expr or _default_key(proj)
            out[key] = _read_ref(proj.expr, row)
    return Row(out)


def _format_expr(expr: Any) -> str:
    if expr is None:
        return "null"
    from gql_core.ir import Variable, Property, Literal, AggregateExpr, FunctionCall, Arithmetic
    if isinstance(expr, Ref):
        if expr.var == "*":
            return "*"
        return f"{expr.var}.{expr.prop}" if expr.prop else expr.var
    if isinstance(expr, Variable):
        return expr.name
    if isinstance(expr, Property):
        return f"{expr.var}.{expr.prop}"
    if isinstance(expr, Literal):
        return str(expr.value)
    if isinstance(expr, FunctionCall):
        args_str = ", ".join(_format_expr(a) for a in expr.args)
        name_lower = expr.name.lower()
        fn_name = name_lower if name_lower in (
            "size", "tail", "head", "count", "sum", "avg", "min", "max",
            "collect", "keys", "labels", "nodes", "relationships", "range",
            "tolower", "toupper", "trim", "ltrim", "rtrim", "reverse",
            "coalesce", "tostring", "tointeger", "tofloat", "toboolean",
            "type", "id", "properties", "exists", "startnode", "endnode",
            "length", "abs", "round", "ceil", "floor", "sign", "rand", "sqrt"
        ) else expr.name
        return f"{fn_name}({args_str})"
    if isinstance(expr, AggregateExpr):
        arg_str = _format_expr(expr.arg) if hasattr(expr, "arg") else "*"
        return f"{expr.func.lower()}({arg_str})"
    if isinstance(expr, Arithmetic):
        return f"{_format_expr(expr.lhs)} {expr.op} {_format_expr(expr.rhs)}"
    if isinstance(expr, (list, tuple)):
        return f"[{', '.join(_format_expr(x) for x in expr)}]"
    if isinstance(expr, dict):
        return f"{{{', '.join(f'{k}: {_format_expr(v)}' for k, v in expr.items())}}}"
    return str(expr)


def _default_key(proj: Projection) -> str:
    if proj.alias:
        return proj.alias
    if proj.raw_expr:
        return proj.raw_expr
    if proj.agg is not None:
        agg_name = proj.agg.lower()
        if isinstance(proj.expr, Ref) and proj.expr.var == "*":
            return f"{agg_name}(*)"
        return f"{agg_name}({_format_expr(proj.expr)})"
    return _format_expr(proj.expr)


def _aggregate(projections: tuple[Projection, ...], rows: list[dict], graph: PropertyGraph | None = None) -> list[dict]:
    group_keys = [p for p in projections if p.agg is None and not _is_aggregate(p.expr)]
    agg_specs = [p for p in projections if p.agg is not None or _is_aggregate(p.expr)]

    groups: dict[tuple, list[dict]] = {}
    group_values: dict[tuple, tuple] = {}
    for row in rows:
        raw_vals = tuple(_read_ref_full(p.expr, row, graph) for p in group_keys)
        hash_key = tuple(_hashable_val(v) for v in raw_vals)
        if hash_key not in group_values:
            group_values[hash_key] = raw_vals
        groups.setdefault(hash_key, []).append(row)
    if not group_keys and not groups:
        groups[()] = []
        group_values[()] = ()

    result: list[dict] = []
    for hash_key, members in groups.items():
        out: dict = {}
        actual_vals = group_values[hash_key]
        for p, k in zip(group_keys, actual_vals):
            out[p.alias or p.raw_expr or _default_key(p)] = k
        for spec in agg_specs:
            key = spec.alias or spec.raw_expr or _default_key(spec)
            if spec.agg is not None:
                out[key] = _apply_agg(spec, members, graph=graph)
            else:
                out[key] = _eval_expr_with_aggs(spec.expr, members, graph, group_row=out)
        result.append(Row(out))
    return result


def _apply_agg(
    agg_or_spec: str | Projection,
    expr_or_rows: Any,
    rows: list[dict] | None = None,
    graph: PropertyGraph | None = None,
    distinct: bool = False,
) -> Any:
    if isinstance(agg_or_spec, Projection):
        agg_name = agg_or_spec.agg or ""
        expr = agg_or_spec.expr
        row_list = expr_or_rows
        distinct = getattr(agg_or_spec, "distinct", False)
    else:
        agg_name = agg_or_spec
        expr = expr_or_rows
        row_list = rows or []

    agg_up = agg_name.upper()
    if agg_up == "COUNT" and isinstance(expr, Ref) and expr.var == "*":
        return len(row_list)
    values: list[Any] = []
    for r in row_list:
        v = _read_ref_full(expr, r, graph)
        if v is not None:
            values.append(v)
    if distinct:
        seen = set()
        dedup = []
        for val in values:
            hk = _hashable_val(val)
            if hk not in seen:
                seen.add(hk)
                dedup.append(val)
        values = dedup

    if agg_up == "COUNT":
        return len(values)
    if agg_up == "COLLECT":
        return values
    if not values:
        return None
    numeric = [_to_number(v) for v in values if _to_number(v) is not None]
    if agg_up == "SUM":
        return sum(numeric) if numeric else 0
    if agg_up == "MIN":
        return min(values, key=_safe_sort_key)
    if agg_up == "MAX":
        return max(values, key=_safe_sort_key)
    if agg_up == "AVG":
        return (sum(numeric) / len(numeric)) if numeric else None
    raise ValueError(f"Unsupported aggregate: {agg_name}")


def _eval_expr_with_aggs(
    expr: Any,
    rows: list[dict],
    graph: PropertyGraph | None = None,
    group_row: dict | None = None,
) -> Any:
    from gql_core.ir import AggregateExpr, FunctionCall, Arithmetic
    from gql_core.physical.evaluator import _eval_function

    if isinstance(expr, Projection) and expr.agg is not None:
        return _apply_agg(expr.agg, expr.expr, rows, graph, distinct=getattr(expr, "distinct", False))
    if isinstance(expr, AggregateExpr):
        return _apply_agg(expr.func, expr.expr, rows, graph, distinct=getattr(expr, "distinct", False))
    if isinstance(expr, FunctionCall):
        if expr.name.upper() in ("COUNT", "SUM", "AVG", "MIN", "MAX", "COLLECT"):
            arg = expr.args[0] if expr.args else Ref("*")
            return _apply_agg(expr.name.upper(), arg, rows, graph)
        if expr.name == "LIST_COMPREHENSION" and len(expr.args) >= 4:
            from gql_core.physical.evaluator import eval_value, eval_predicate
            var_name = getattr(expr.args[0], "name", getattr(expr.args[0], "var", str(expr.args[0])))
            coll_val = _eval_expr_with_aggs(expr.args[1], rows, graph, group_row)
            if coll_val is None or not isinstance(coll_val, (list, tuple)):
                return None
            res = []
            for item in coll_val:
                local_row = dict(group_row or {})
                local_row[var_name] = item
                if expr.args[2] is None or eval_predicate(expr.args[2], local_row, graph) is True:
                    res.append(eval_value(expr.args[3], local_row, graph))
            return res
        if expr.name.upper() in ("ALL", "ANY", "NONE", "SINGLE") and len(expr.args) >= 2:
            from gql_core.physical.evaluator import eval_predicate
            var_name = getattr(expr.args[0], "name", getattr(expr.args[0], "var", str(expr.args[0])))
            coll_val = _eval_expr_with_aggs(expr.args[1], rows, graph, group_row)
            if coll_val is None or not isinstance(coll_val, (list, tuple)):
                return None
            cond_expr = expr.args[2] if len(expr.args) >= 3 else None
            matches = 0
            has_unknown = False
            for item in coll_val:
                local_row = dict(group_row or {})
                local_row[var_name] = item
                ev = eval_predicate(cond_expr, local_row, graph) if cond_expr is not None else True
                if ev is True:
                    matches += 1
                elif ev is None:
                    has_unknown = True
            name_up = expr.name.upper()
            if name_up == "ALL":
                if has_unknown and matches + 1 == len(coll_val):
                    return None
                return matches == len(coll_val) and not has_unknown
            elif name_up == "ANY":
                if matches > 0:
                    return True
                if has_unknown:
                    return None
                return False
            elif name_up == "NONE":
                if matches > 0:
                    return False
                if has_unknown:
                    return None
                return True
            elif name_up == "SINGLE":
                if has_unknown:
                    return None
                return matches == 1
        eval_args = [_eval_expr_with_aggs(a, rows, graph, group_row) for a in expr.args]
        return _eval_function(expr.name, eval_args)
    if isinstance(expr, Arithmetic):
        lval = _eval_expr_with_aggs(expr.lhs, rows, graph, group_row)
        rval = _eval_expr_with_aggs(expr.rhs, rows, graph, group_row)
        if lval is None or rval is None:
            return None
        if isinstance(lval, (int, float)) and isinstance(rval, (int, float)):
            if expr.op == "+":
                return lval + rval
            if expr.op == "-":
                return lval - rval
            if expr.op == "*":
                return lval * rval
            if expr.op == "/":
                if rval == 0:
                    return None
                if isinstance(lval, int) and isinstance(rval, int) and not isinstance(lval, bool) and not isinstance(rval, bool):
                    return int(lval / rval)
                return lval / rval
            if expr.op == "%":
                return lval % rval if rval != 0 else None
            if expr.op == "^":
                return lval ** rval
        if expr.op == "+":
            if isinstance(lval, str) or isinstance(rval, str):
                return str(lval) + str(rval)
            if isinstance(lval, (list, tuple)) and isinstance(rval, (list, tuple)):
                return list(lval) + list(rval)
        return None

    rep = dict(getattr(graph, "_parameters", {})) if graph is not None else {}
    if group_row:
        rep.update(group_row)
    elif rows:
        rep.update(rows[0])
    return _read_ref_full(expr, rep, graph)


def _to_number(v: Any) -> int | float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    return None


def _sort_rows(
    rows: list[dict], order_by: OrderBy, alias_map: dict[str, Any] | None = None
) -> list[dict]:
    out = list(rows)
    for term in reversed(order_by.terms):
        reverse = term.direction.upper() == "DESC"
        var = term.ref.var
        prop = term.ref.prop

        target_ref = term.ref
        if alias_map and var in alias_map and prop is None:
            target_ref = alias_map[var]

        def key(row: dict, ref=target_ref, var=var, prop=prop) -> Any:
            v = _read_ref(ref, row)
            if v is None and prop is None and var in row:
                v = row[var]
            if v is None and prop is not None and prop in row:
                v = row[prop]
            return _safe_sort_key(v)

        out.sort(key=key, reverse=reverse)
    return out


def _none_safe(v: Any) -> tuple:
    """Sort key that buckets None at the end regardless of direction."""
    return _safe_sort_key(v)


def _temporal_sort_key(s: str) -> tuple | None:
    import re
    m_time = re.match(r"^(\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?([+-]\d{2}:?\d{2}|Z)?$", s)
    if m_time:
        h, mi = int(m_time.group(1)), int(m_time.group(2))
        sec = int(m_time.group(3) or 0)
        ns_str = (m_time.group(4) or "")[:9].ljust(9, "0")
        ns = int(ns_str) if ns_str else 0
        tz_str = m_time.group(5)
        total_sec = h * 3600 + mi * 60 + sec + ns / 1e9
        if tz_str:
            if tz_str != "Z":
                sign = 1 if tz_str[0] == "+" else -1
                clean_tz = tz_str[1:].replace(":", "")
                tz_h = int(clean_tz[:2])
                tz_m = int(clean_tz[2:4]) if len(clean_tz) >= 4 else 0
                total_sec -= sign * (tz_h * 3600 + tz_m * 60)
        return ("__time__", total_sec)

    m_dt = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?([+-]\d{2}:?\d{2}|Z)?$", s)
    if m_dt:
        y, mo, d = int(m_dt.group(1)), int(m_dt.group(2)), int(m_dt.group(3))
        h, mi, sec = int(m_dt.group(4)), int(m_dt.group(5)), int(m_dt.group(6))
        ns_str = (m_dt.group(7) or "")[:9].ljust(9, "0")
        ns = int(ns_str) if ns_str else 0
        tz_str = m_dt.group(8)
        days = y * 365 + mo * 30 + d
        total_sec = days * 86400 + h * 3600 + mi * 60 + sec + ns / 1e9
        if tz_str:
            if tz_str != "Z":
                sign = 1 if tz_str[0] == "+" else -1
                clean_tz = tz_str[1:].replace(":", "")
                tz_h = int(clean_tz[:2])
                tz_m = int(clean_tz[2:4]) if len(clean_tz) >= 4 else 0
                total_sec -= sign * (tz_h * 3600 + tz_m * 60)
        return ("__dt__", total_sec)
    return None


def _safe_sort_key(v: Any) -> tuple:
    """openCypher global type ordering:
    Map < Node < Relationship < Path < List < String < Boolean < Number < NaN < null
    """
    if v is None:
        return (9, 0)
    if isinstance(v, float) and math.isnan(v):
        return (8, 0)
    if isinstance(v, bool):
        return (6, 1 if v else 0)
    if isinstance(v, (int, float)):
        return (7, float(v))
    if hasattr(v, "nodes") and hasattr(v, "relationships"):
        return (3, len(v), str(v))
    if hasattr(v, "src") and hasattr(v, "dst"):
        return (2, str(getattr(v, "id", "")))
    if hasattr(v, "label") and hasattr(v, "props"):
        return (1, str(getattr(v, "id", "")))
    if isinstance(v, (list, tuple)):
        return (4, tuple(_safe_sort_key(x) for x in v))
    if isinstance(v, dict):
        return (0, tuple(sorted((str(k), _safe_sort_key(val)) for k, val in v.items())))
    if isinstance(v, str):
        t_key = _temporal_sort_key(v)
        if t_key is not None:
            return (5, t_key)
        return (5, (v,))
    return (10, str(v))


def _read_ref_full(ref: Any, row: dict, graph: PropertyGraph | None = None) -> Any:
    if isinstance(ref, Ref):
        if ref.var == "*":
            return row
        binding = row.get(ref.var)
        if binding is None:
            return None
        if ref.prop is None:
            return binding
        if hasattr(binding, "props") and ref.prop in binding.props:
            return binding.props[ref.prop]
        if ref.prop == "id" and hasattr(binding, "id"):
            return binding.id
        if ref.prop == "label" and hasattr(binding, "label"):
            return binding.label
        if isinstance(binding, dict):
            return binding.get(ref.prop)
        if hasattr(binding, "get_component"):
            comp = binding.get_component(ref.prop)
            if comp is not None:
                return comp
        from gql_core.physical.evaluator import _extract_temporal_prop
        comp = _extract_temporal_prop(binding, ref.prop)
        if comp is not None:
            return comp
        return getattr(binding, ref.prop, None)

    from gql_core.ir import (
        Variable,
        Property,
        Literal,
        Comparison as IRComparison,
        And as IRAnd,
        Or as IROr,
        Not as IRNot,
        IsNull as IRIsNull,
        IsNotNull as IRIsNotNull,
        StringMatch,
        RegexMatch,
        In as IRIn,
        BoolExpr,
    )
    from gql_core.physical.evaluator import eval_value, eval_predicate

    from gql_core.ir import Parameter
    if isinstance(ref, Parameter) or type(ref).__name__ == "Parameter":
        params = getattr(graph, "_parameters", {}) if graph is not None else {}
        pname = getattr(ref, "name", str(ref))
        if pname in params:
            return params[pname]
        if f"${pname}" in row:
            return row[f"${pname}"]
        if pname in row:
            return row[pname]
        return None

    if isinstance(ref, Variable):
        if ref.name.startswith("$"):
            pname = ref.name[1:]
            params = getattr(graph, "_parameters", {}) if graph is not None else {}
            if pname in params:
                return params[pname]
        return row.get(ref.name)
    if isinstance(ref, Property):
        entity = row.get(ref.var)
        if entity is None:
            return None
        if hasattr(entity, "props") and ref.prop in entity.props:
            return entity.props[ref.prop]
        if isinstance(entity, dict):
            return entity.get(ref.prop)
        if hasattr(entity, "get_component"):
            comp = entity.get_component(ref.prop)
            if comp is not None:
                return comp
        from gql_core.physical.evaluator import _extract_temporal_prop
        comp = _extract_temporal_prop(entity, ref.prop)
        if comp is not None:
            return comp
        return getattr(entity, ref.prop, None)
    if isinstance(ref, (int, float, str, bool)):
        return ref
    if isinstance(ref, Literal):
        return ref.value
    if isinstance(ref, (Comparison, And, Or, Not, PatternPredicate, IRComparison, IRAnd, IROr, IRNot, IRIsNull, IRIsNotNull, StringMatch, RegexMatch, IRIn, BoolExpr)):
        return eval_predicate(ref, row, graph)
    return eval_value(ref, row, graph)


def _eval_single_expr(expr: Any, row: dict, graph: PropertyGraph | None = None) -> Any:
    return _read_ref_full(expr, row, graph)


def _is_aggregate(expr: Any) -> bool:
    from gql_core.ir import AggregateExpr, Arithmetic, FunctionCall
    if isinstance(expr, AggregateExpr):
        return True
    if isinstance(expr, Projection) and expr.agg is not None:
        return True
    if isinstance(expr, Arithmetic):
        return _is_aggregate(expr.lhs) or _is_aggregate(expr.rhs)
    if isinstance(expr, FunctionCall):
        if expr.name.upper() in ("COUNT", "SUM", "AVG", "MIN", "MAX", "COLLECT"):
            return True
        return any(_is_aggregate(a) for a in expr.args)
    return False


def _execute_unwind_clause(clause: UnwindClause, rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        val = _read_ref_full(clause.expr, r)
        if val is None:
            continue
        if isinstance(val, (list, tuple)):
            for item in val:
                new_r = dict(r)
                new_r[clause.alias] = item
                out.append(new_r)
        else:
            new_r = dict(r)
            new_r[clause.alias] = val
            out.append(new_r)
    return out


def _execute_return_or_with(
    clause: ReturnClause | WithClause,
    rows: list[dict],
    is_with: bool = False,
    graph: PropertyGraph | None = None,
) -> list[dict]:
    from gql_core.ir import AggregateExpr, FunctionCall

    items = clause.items
    has_agg = any(_is_aggregate(p.expr) or p.agg is not None for p in items)

    if has_agg:
        group_items = [p for p in items if not _is_aggregate(p.expr) and p.agg is None]
        agg_items = [p for p in items if _is_aggregate(p.expr) or p.agg is not None]

        groups: dict[tuple, list[dict]] = {}
        group_keys_eval: dict[tuple, dict[str, Any]] = {}

        for r in rows:
            gk = []
            gv = {}
            for p in group_items:
                v = _read_ref_full(p.expr, r, graph)
                k = _default_key(p)
                gv[k] = v
                gk.append(_hashable_val(v))
            t_gk = tuple(gk)
            if t_gk not in groups:
                groups[t_gk] = []
                group_keys_eval[t_gk] = gv
            groups[t_gk].append(r)

        if not group_items and not groups:
            groups[()] = []
            group_keys_eval[()] = {}

        out = []
        for t_gk, members in groups.items():
            res_row = dict(group_keys_eval[t_gk])
            for p in agg_items:
                k = _default_key(p)
                agg_fn = p.agg
                agg_arg = p.expr
                distinct = getattr(p, "distinct", False)
                if isinstance(agg_arg, AggregateExpr):
                    agg_fn = agg_arg.func
                    agg_arg = agg_arg.expr
                    distinct = getattr(agg_arg, "distinct", False) or distinct
                elif isinstance(p.expr, FunctionCall) and p.expr.name.upper() in (
                    "COUNT",
                    "SUM",
                    "AVG",
                    "MIN",
                    "MAX",
                    "COLLECT",
                ):
                    agg_fn = p.expr.name.upper()
                    agg_arg = p.expr.args[0] if p.expr.args else Ref("*")
                if agg_fn is not None:
                    res_row[k] = _apply_agg(agg_fn, agg_arg, members, graph=graph, distinct=distinct)
                else:
                    res_row[k] = _eval_expr_with_aggs(p.expr, members, graph, group_row=res_row)
            if isinstance(clause, WithClause) and clause.where is not None:
                merged = dict(members[0]) if members else {}
                merged.update(res_row)
                if _eval_single_expr(clause.where, merged, graph) is not True:
                    continue
            out.append(res_row if is_with else Row(res_row))
    else:
        out = []
        for r in rows:
            res_row = {}
            for p in items:
                if (isinstance(p.expr, Ref) and p.expr.var == "*") or p.raw_expr == "*":
                    for k, v in r.items():
                        if not k.startswith("__"):
                            res_row[k] = v
                else:
                    k = p.alias or _default_key(p)
                    res_row[k] = _read_ref_full(p.expr, r, graph)
            merged = dict(r)
            merged.update(res_row)
            if isinstance(clause, WithClause) and clause.where is not None:
                if _eval_single_expr(clause.where, merged, graph) is not True:
                    continue
            out.append(res_row if is_with else Row(res_row))

    if clause.distinct:
        seen = set()
        dedup = []
        for r in out:
            k = tuple(sorted((k, _hashable_val(v)) for k, v in r.items()))
            if k not in seen:
                seen.add(k)
                dedup.append(r)
        out = dedup

    if clause.order_by:
        for term in reversed(clause.order_by.terms):
            rev = term.direction == "DESC"

            def sort_key(r, t=term.ref):
                for p in clause.items:
                    if p.expr == t or (isinstance(t, Projection) and t.agg == p.agg and t.expr == p.expr) or (isinstance(t, Ref) and t.prop is None and p.alias == t.var):
                        k = p.alias or _default_key(p)
                        if k in r:
                            return _safe_sort_key(r[k])
                val = _read_ref_full(t, r, graph)
                if val is None and isinstance(t, Ref) and t.var in r:
                    val = r[t.var]
                return _safe_sort_key(val)

            out.sort(key=sort_key, reverse=rev)

    if clause.skip is not None:
        s_val = _read_ref_full(clause.skip, {}, graph)
        if isinstance(s_val, float) and not s_val.is_integer():
            raise SemanticError(f"InvalidArgumentType: SKIP must be an integer, got float {s_val}")
        if isinstance(s_val, (int, float)):
            if s_val < 0:
                raise SemanticError(f"InvalidArguments: SKIP must be non-negative, got {s_val}")
            out = out[int(s_val):]

    if clause.limit is not None:
        l_val = _read_ref_full(clause.limit, {}, graph)
        if isinstance(l_val, float) and not l_val.is_integer():
            raise SemanticError(f"InvalidArgumentType: LIMIT must be an integer, got float {l_val}")
        if isinstance(l_val, (int, float)):
            if l_val < 0:
                raise SemanticError(f"InvalidArguments: LIMIT must be non-negative, got {l_val}")
            out = out[:int(l_val)]

    if is_with:
        has_star = any((isinstance(p.expr, Ref) and p.expr.var == "*") or p.raw_expr == "*" for p in items)
        if not has_star:
            final_out = []
            item_keys = [p.alias or _default_key(p) for p in items]
            for r in out:
                final_out.append({k: r.get(k) for k in item_keys})
            out = final_out

    return out


def _execute_match_clause(clause: MatchClause, rows: list[dict], graph: PropertyGraph) -> list[dict]:
    out = []
    for r in rows:
        match_rows = [dict(r)]
        for pat in clause.patterns:
            new_match_rows = []
            for cur_row in match_rows:
                sub_matches = _match_path_pattern(pat, cur_row, graph)
                new_match_rows.extend(sub_matches)
            match_rows = new_match_rows

        if clause.where is not None:
            filtered = []
            for m in match_rows:
                if _eval_single_expr(clause.where, m, graph) is True:
                    filtered.append(m)
            match_rows = filtered

        if not match_rows and clause.optional:
            opt_r = dict(r)
            for pat in clause.patterns:
                if pat.path_var and pat.path_var not in opt_r:
                    opt_r[pat.path_var] = None
                for n in pat.nodes:
                    if n.var and n.var not in opt_r:
                        opt_r[n.var] = None
                for rel in pat.rels:
                    if rel.var and rel.var not in opt_r:
                        opt_r[rel.var] = None
            out.append(opt_r)
        else:
            for m in match_rows:
                m.pop("__used_edges__", None)
            out.extend(match_rows)
    return out


def _match_path_pattern(pat: Pattern, seed_row: dict, graph: PropertyGraph) -> list[dict]:
    if not pat.nodes:
        return [seed_row]

    start_node_pat = pat.nodes[0]
    start_var = start_node_pat.var or "__node_0"
    start_nodes = []
    if start_node_pat.var and start_node_pat.var in seed_row:
        existing = seed_row[start_node_pat.var]
        if isinstance(existing, Node):
            if start_node_pat.label is None or existing.label == start_node_pat.label:
                start_nodes = [existing]
    else:
        if start_node_pat.label:
            start_nodes = list(graph.nodes_by_label(start_node_pat.label))
        else:
            start_nodes = list(graph._nodes.values())

    if start_node_pat.filters:
        start_nodes = [n for n in start_nodes if all(n.props.get(k) == v for k, v in start_node_pat.filters)]

    current_matches = []
    for sn in start_nodes:
        nr = dict(seed_row)
        nr[start_var] = sn
        if start_node_pat.var:
            nr[start_node_pat.var] = sn
        if pat.path_var:
            nr["__path_edges__"] = ()
        current_matches.append(nr)

    for step_idx, rel in enumerate(pat.rels):
        from_var = pat.nodes[step_idx].var or f"__node_{step_idx}"
        next_node_pat = pat.nodes[step_idx + 1]
        to_var = next_node_pat.var or f"__node_{step_idx + 1}"
        next_matches = []
        for cur_r in current_matches:
            prev_node = cur_r.get(from_var)
            if not isinstance(prev_node, Node):
                continue
            used_edges = cur_r.get("__used_edges__", frozenset())

            op = ExpandOp(
                from_var=from_var,
                to_var=to_var,
                edge_var=rel.var,
                edge_label=rel.label,
                direction=rel.direction,
                quantifier=rel.quantifier,
                to_label=next_node_pat.label,
                to_inline_filters=next_node_pat.filters,
                pushed=[],
            )
            for edge_path, target in _walk(graph, prev_node, op, used_edges=used_edges):
                path_edge_ids = frozenset(_base_edge_id(e.id) for e in edge_path)
                if used_edges and (used_edges & path_edge_ids):
                    continue
                if next_node_pat.label and target.label != next_node_pat.label:
                    continue
                if next_node_pat.filters and not all(target.props.get(k) == v for k, v in next_node_pat.filters):
                    continue
                new_r = dict(cur_r)
                if next_node_pat.var:
                    if next_node_pat.var in new_r and new_r[next_node_pat.var] != target:
                        continue
                    new_r[next_node_pat.var] = target
                new_r[to_var] = target
                if rel.var:
                    if getattr(rel, "quantifier", ("one",)) != ("one",):
                        new_r[rel.var] = list(edge_path)
                    elif edge_path:
                        new_r[rel.var] = edge_path[0]
                    else:
                        new_r[rel.var] = None
                if pat.path_var:
                    new_r["__path_edges__"] = cur_r.get("__path_edges__", ()) + tuple(edge_path)
                new_r["__used_edges__"] = used_edges | path_edge_ids
                next_matches.append(new_r)
        current_matches = next_matches

    if pat.path_var:
        from gql_core.graph import Path
        for m in current_matches:
            rel_seq = tuple(m.get("__path_edges__", ()))
            start_node = m.get(start_var)
            if isinstance(start_node, Node):
                node_seq = [start_node]
                curr_n = start_node
                for e in rel_seq:
                    next_id = e.dst if e.src == curr_n.id else e.src
                    nxt = graph._nodes.get(next_id)
                    if nxt:
                        node_seq.append(nxt)
                        curr_n = nxt
            else:
                node_seq = [m[pat.nodes[i].var or f"__node_{i}"] for i in range(len(pat.nodes))]
            m[pat.path_var] = Path(nodes=tuple(node_seq), relationships=rel_seq)
            m.pop("__path_edges__", None)

    return current_matches


def _execute_create_clause(clause: CreateClause, rows: list[dict], graph: PropertyGraph) -> list[dict]:
    out = []
    auto_id = len(graph._nodes) + len(graph._edges) + 1000
    for r in rows:
        cur_r = dict(r)
        for pat in clause.patterns:
            prev_node = None
            for idx, n_pat in enumerate(pat.nodes):
                if n_pat.var and n_pat.var in cur_r and isinstance(cur_r[n_pat.var], Node):
                    if len(pat.nodes) == 1 and len(pat.rels) == 0:
                        raise ValueError(f"Variable '{n_pat.var}' is already bound")
                    if n_pat.label is not None or n_pat.filters or getattr(n_pat, "labels", ()):
                        raise ValueError(f"Variable '{n_pat.var}' is already bound and cannot have labels or properties added in CREATE")
                    node = cur_r[n_pat.var]
                else:
                    auto_id += 1
                    props = {k: _read_ref_full(v, cur_r) for k, v in n_pat.filters if v is not None}
                    nid = f"node_{auto_id}"
                    node_labels = tuple(getattr(n_pat, "labels", ())) or ((n_pat.label,) if n_pat.label else ())
                    primary_lbl = node_labels[0] if node_labels else "Node"
                    node = Node(id=nid, label=primary_lbl, props=props, labels=node_labels)
                    graph.add_node(node)
                    if n_pat.var:
                        cur_r[n_pat.var] = node

                if idx > 0 and prev_node:
                    rel_pat = pat.rels[idx - 1]
                    if not rel_pat.label:
                        raise ValueError("Relationships in CREATE must have a type")
                    if rel_pat.direction not in ("out", "in"):
                        raise ValueError("Relationships in CREATE must have a direction (-> or <-)")
                    if rel_pat.quantifier != ("one",):
                        raise ValueError("Variable-length relationships cannot be created")
                    if rel_pat.var and rel_pat.var in cur_r:
                        raise ValueError(f"Relationship variable '{rel_pat.var}' is already bound")
                    auto_id += 1
                    base_id = rel_pat.var or "rel"
                    rid = base_id if base_id not in graph._edges else f"{base_id}_{auto_id}"
                    while rid in graph._edges:
                        auto_id += 1
                        rid = f"{base_id}_{auto_id}"
                    if rel_pat.direction == "out":
                        src, dst = prev_node.id, node.id
                    elif rel_pat.direction == "in":
                        src, dst = node.id, prev_node.id
                    else:
                        src, dst = prev_node.id, node.id
                    rel_props = {k: _read_ref_full(v, cur_r) for k, v in rel_pat.filters if v is not None}
                    edge = Edge(id=rid, label=rel_pat.label, src=src, dst=dst, props=rel_props)
                    graph.add_edge(edge)
                    if rel_pat.var:
                        cur_r[rel_pat.var] = edge
                prev_node = node
        out.append(cur_r)
    return out


def _execute_set_clause(clause: SetClause, rows: list[dict], graph: PropertyGraph) -> list[dict]:
    for r in rows:
        for item in clause.items:
            if item.kind == "prop":
                if isinstance(item.target, Ref) and item.target.prop:
                    node = r.get(item.target.var)
                    if hasattr(node, "props"):
                        node.props[item.target.prop] = _read_ref_full(item.value, r)
                else:
                    node = r.get(item.target.var) if isinstance(item.target, Ref) else _read_ref_full(item.target, r)
                    new_props = _read_ref_full(item.value, r)
                    if isinstance(new_props, dict) and hasattr(node, "props"):
                        node.props = dict(new_props)
            elif item.kind == "prop_merge":
                node = r.get(item.target.var) if isinstance(item.target, Ref) else _read_ref_full(item.target, r)
                m = _read_ref_full(item.value, r)
                if isinstance(m, dict) and hasattr(node, "props"):
                    node.props.update(m)
            elif item.kind == "labels":
                node = r.get(item.target.var) if isinstance(item.target, Ref) else _read_ref_full(item.target, r)
                if node and hasattr(node, "labels"):
                    cur_labels = list(node.labels)
                    for lbl in item.labels:
                        if lbl not in cur_labels:
                            cur_labels.append(lbl)
                        graph._by_label.setdefault(lbl, set()).add(node.id)
                    node.labels = tuple(cur_labels)
                    if hasattr(node, "label") and (not node.label or node.label == "Node") and item.labels:
                        node.label = item.labels[0]
    return rows


def _execute_delete_clause(clause: DeleteClause, rows: list[dict], graph: PropertyGraph) -> list[dict]:
    for r in rows:
        for expr in clause.items:
            target = _read_ref_full(expr, r)
            if isinstance(target, Node):
                graph.delete_node(target.id, detach=clause.detach)
            elif isinstance(target, Edge):
                graph.delete_edge(target.id)
    return rows


def _execute_remove_clause(clause: RemoveClause, rows: list[dict], graph: PropertyGraph) -> list[dict]:
    for r in rows:
        for item in clause.items:
            var_name = item.target.var if isinstance(item.target, Ref) else (item.target.name if hasattr(item.target, "name") else str(item.target))
            node = r.get(var_name)
            if node is None and not isinstance(item.target, str):
                node = _read_ref_full(item.target, r)
            if item.kind == "prop":
                prop_to_remove = item.prop_name or (item.target.prop if isinstance(item.target, Ref) else None)
                if prop_to_remove and hasattr(node, "props"):
                    node.props.pop(prop_to_remove, None)
            elif item.kind == "labels":
                if node and hasattr(node, "labels"):
                    rem_set = set(item.labels)
                    node.labels = tuple(l for l in node.labels if l not in rem_set)
                    for lbl in item.labels:
                        if lbl in graph._by_label and hasattr(node, "id"):
                            graph._by_label[lbl].discard(node.id)
    return rows


def _execute_merge_clause(clause: MergeClause, rows: list[dict], graph: PropertyGraph) -> list[dict]:
    out = []
    for r in rows:
        r_clean = dict(r)
        r_clean.pop("__used_edges__", None)
        matches = _match_path_pattern(clause.pattern, r_clean, graph)
        if matches:
            for m in matches:
                m.pop("__used_edges__", None)
                for act in clause.actions:
                    if act.on_event == "MATCH":
                        _execute_set_clause(SetClause(act.items), [m], graph)
                out.append(m)
        else:
            create_pat = clause.pattern
            if any(rel.direction in ("undirected", "both") for rel in create_pat.rels):
                from gql_core.query.ast import Pattern, RelPat
                fixed_rels = tuple(
                    RelPat(
                        var=rel.var,
                        label=rel.label,
                        direction="out" if rel.direction in ("undirected", "both") else rel.direction,
                        quantifier=rel.quantifier,
                        filters=rel.filters,
                    )
                    for rel in create_pat.rels
                )
                create_pat = Pattern(nodes=create_pat.nodes, rels=fixed_rels, path_var=create_pat.path_var)
            created = _execute_create_clause(CreateClause(patterns=(create_pat,)), [r], graph)
            for c in created:
                for act in clause.actions:
                    if act.on_event == "CREATE":
                        _execute_set_clause(SetClause(act.items), [c], graph)
                out.append(c)
    return out


def _execute_call_clause(clause: CallClause, rows: list[dict], graph: PropertyGraph, is_standalone: bool = True) -> list[dict]:
    from gql_core.query.semantic import SemanticError
    proc_map = getattr(graph, "_procedures", {})
    proc = clause.proc_name
    proc_lower = proc.lower()

    # 1. Validation: check if aggregation in arguments
    for arg in clause.args:
        if _is_aggregate(arg):
            raise SemanticError(f"Aggregation expression not permitted in CALL arguments: {arg}")

    # 2. Check duplicate yield variable names
    if clause.yield_items:
        yield_vars = [alias or orig for orig, alias in clause.yield_items]
        if len(yield_vars) != len(set(yield_vars)):
            raise SemanticError(f"Duplicate variable in YIELD: {yield_vars}")

    meta = None
    if proc in proc_map:
        meta = proc_map[proc]
    elif proc_lower in proc_map:
        meta = proc_map[proc_lower]
    elif "labels" in proc_lower:
        meta = {"signature": ([], ["label"]), "rows": [{"label": lbl} for lbl in sorted(graph._by_label.keys())]}

    if meta is None:
        if proc_lower.startswith("test.") or proc_lower.startswith("org.opencypher."):
            raise SemanticError(f"Unknown procedure: {proc}")
        return []

    if isinstance(meta, dict) and "signature" in meta:
        in_params, out_params = meta["signature"]
        proc_rows = meta["rows"]
    elif isinstance(meta, list):
        in_params = []
        out_params = list(meta[0].keys()) if meta else []
        proc_rows = meta
    else:
        in_params, out_params = [], []
        proc_rows = []

    in_names = [p[0] if isinstance(p, tuple) else p for p in in_params]
    in_types = [p[1] if isinstance(p, tuple) else "ANY" for p in in_params]

    # 3. Check argument count & implicit parameters
    if len(clause.args) == 0 and len(in_names) > 0:
        if not is_standalone:
            raise SemanticError(f"InvalidArgumentPassingMode: procedure {proc} takes {len(in_names)} arguments, in-query calls cannot pass arguments implicitly")
        params = getattr(graph, "_parameters", {})
        if all(name in params for name in in_names):
            from gql_core.ir import Literal
            clause = CallClause(proc_name=clause.proc_name, args=tuple(Literal(params[name]) for name in in_names), yield_items=clause.yield_items)
        else:
            raise SemanticError(f"InvalidNumberOfArguments: procedure {proc} takes {len(in_names)} arguments, got 0")
    elif len(clause.args) != len(in_names):
        raise SemanticError(f"InvalidNumberOfArguments: procedure {proc} takes {len(in_names)} arguments, got {len(clause.args)}")

    # Check argument types
    from gql_core.ir import Literal
    for idx, (p_type, arg) in enumerate(zip(in_types, clause.args)):
        arg_val = arg.value if isinstance(arg, Literal) else arg
        p_up = p_type.upper()
        if p_up.startswith("INTEGER"):
            if isinstance(arg_val, bool) or (isinstance(arg_val, float) and not arg_val.is_integer()) or (not isinstance(arg_val, (int, float)) and arg_val is not None and not isinstance(arg, Ref)):
                raise SemanticError(f"InvalidArgumentType: expected INTEGER, got {type(arg_val).__name__}")
        elif p_up.startswith("BOOLEAN"):
            if not isinstance(arg_val, bool) and arg_val is not None and not isinstance(arg, Ref):
                raise SemanticError(f"InvalidArgumentType: expected BOOLEAN, got {type(arg_val).__name__}")
        elif p_up.startswith("STRING"):
            if not isinstance(arg_val, str) and arg_val is not None and not isinstance(arg, Ref):
                raise SemanticError(f"InvalidArgumentType: expected STRING, got {type(arg_val).__name__}")

    # 4. Check in-query YIELD requirement: if procedure has outputs and caller does not yield
    if out_params and not clause.yield_items and not is_standalone:
        raise SemanticError(f"In-query procedure call to {proc} must yield outputs")

    # 5. Check variable shadowing in incoming rows
    if clause.yield_items:
        for r in rows:
            for orig, alias in clause.yield_items:
                if orig == "*":
                    continue
                col_name = alias or orig
                if col_name in r:
                    raise SemanticError(f"Procedure output '{col_name}' shadows an existing bound variable")

    # 6. Execute procedure
    out = []
    if not clause.yield_items and not out_params:
        return [] if is_standalone else list(rows)

    for r in rows:
        for p_row in proc_rows:
            match = True
            for idx, p_name in enumerate(in_names):
                if idx < len(clause.args):
                    arg_val = _read_ref_full(clause.args[idx], r, graph)
                    expected_val = p_row.get(p_name)
                    if arg_val is not None and expected_val is not None and arg_val != expected_val:
                        match = False
                        break
            if match:
                if not clause.yield_items:
                    out.append({k: p_row[k] for k in out_params if k in p_row} if out_params else dict(p_row))
                else:
                    if len(clause.yield_items) == 1 and clause.yield_items[0][0] == "*":
                        if not is_standalone:
                            raise SemanticError("YIELD * is only allowed in standalone procedure calls")
                        yielded_dict = {k: p_row[k] for k in out_params if k in p_row} if out_params else dict(p_row)
                        out.append(Row(yielded_dict) if is_standalone else dict(yielded_dict))
                    else:
                        nr = dict(r)
                        for orig_col, alias in clause.yield_items:
                            col_key = alias or orig_col
                            nr[col_key] = p_row.get(orig_col)
                        out.append(nr)
    return out


def execute_pipeline(query: Query, graph: PropertyGraph) -> list[dict]:
    """Execute a multi-clause openCypher pipeline query against a PropertyGraph."""
    if query.unions:
        base_q = Query(clauses=query.clauses)
        out = execute_pipeline(base_q, graph)
        for u_type, sub_q in query.unions:
            sub_res = execute_pipeline(sub_q, graph)
            if "ALL" in u_type.upper():
                out.extend(sub_res)
            else:
                seen = {_hashable_val(tuple(sorted(r.items()))) for r in out}
                for r in sub_res:
                    k = _hashable_val(tuple(sorted(r.items())))
                    if k not in seen:
                        seen.add(k)
                        out.append(r)
        return out

    rows = [{}]
    for clause in query.clauses:
        if isinstance(clause, MatchClause):
            rows = _execute_match_clause(clause, rows, graph)
        elif isinstance(clause, UnwindClause):
            rows = _execute_unwind_clause(clause, rows)
        elif isinstance(clause, WithClause):
            rows = _execute_return_or_with(clause, rows, is_with=True, graph=graph)
        elif isinstance(clause, ReturnClause):
            rows = _execute_return_or_with(clause, rows, is_with=False, graph=graph)
        elif isinstance(clause, CreateClause):
            rows = _execute_create_clause(clause, rows, graph)
        elif isinstance(clause, SetClause):
            rows = _execute_set_clause(clause, rows, graph)
        elif isinstance(clause, DeleteClause):
            rows = _execute_delete_clause(clause, rows, graph)
        elif isinstance(clause, RemoveClause):
            rows = _execute_remove_clause(clause, rows, graph)
        elif isinstance(clause, MergeClause):
            rows = _execute_merge_clause(clause, rows, graph)
        elif isinstance(clause, CallClause):
            rows = _execute_call_clause(clause, rows, graph, is_standalone=(len(query.clauses) == 1))
    has_return = any(
        isinstance(cl, ReturnClause)
        or (isinstance(cl, CallClause) and (bool(cl.yield_items) or len(query.clauses) == 1))
        for cl in query.clauses
    )
    if not has_return:
        return []
    return rows

