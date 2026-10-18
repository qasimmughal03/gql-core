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
    Projection,
    Query,
    Ref,
)
from gql_core.query.parser import parse
from gql_core.query.planner import (
    ExpandOp,
    FilterOp,
    JoinOp,
    Plan,
    ProjectOp,
    ScanOp,
    plan as plan_query,
)
from gql_core.query.semantic import validate_query


def execute(plan_obj: Plan, graph: PropertyGraph) -> list[dict]:
    rows: Iterable[dict] = [{}]
    for op in plan_obj.ops:
        rows = _dispatch(op, rows, graph)
    if not isinstance(rows, list):
        rows = list(rows)
    return rows  # type: ignore[return-value]


def run(
    source: str,
    graph: PropertyGraph,
    schema_path: str | Path | None = None,
) -> list[dict]:
    """Convenience: parse + plan + execute in one call.

    When schema_path is provided, semantic validation runs against that
    ontology. Without it, only structural checks (variable binding) are
    performed.
    """
    query = parse(source)
    validate_query(query, schema_path=schema_path)
    return execute(plan_query(query, graph), graph)


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
        return _project(op, rows)
    raise TypeError(f"Unknown op: {type(op).__name__}")


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
    raise TypeError(f"Unknown expression: {type(expr).__name__}")


def _eval_comparison(cmp: Comparison, row: dict) -> bool | None:
    lhs_value = _read_ref(cmp.lhs, row)
    return _apply_op(cmp.op, lhs_value, cmp.rhs)


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


def _read_ref(ref: Ref, row: dict) -> Any:
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
    if hasattr(v, "id"):
        return ("__entity__", getattr(v, "id"))
    return v


def _project(op: ProjectOp, rows: Iterable[dict]) -> list[dict]:
    materialized = list(rows)
    has_agg = any(p.agg is not None for p in op.projections)
    alias_map = {p.alias: p.expr for p in op.projections if p.alias}
    if has_agg:
        out = _aggregate(op.projections, materialized)
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


def _project_row(projections: tuple[Projection, ...], row: dict) -> dict:
    out: dict = {}
    for proj in projections:
        key = proj.alias or _default_key(proj)
        out[key] = _read_ref(proj.expr, row)
    return out


def _default_key(proj: Projection) -> str:
    if proj.agg is not None:
        if proj.expr.var == "*":
            return proj.agg.lower()
        return f"{proj.agg.lower()}_{proj.expr.var}" + (
            f"_{proj.expr.prop}" if proj.expr.prop else ""
        )
    return proj.expr.prop or proj.expr.var


def _aggregate(projections: tuple[Projection, ...], rows: list[dict]) -> list[dict]:
    group_keys = [p for p in projections if p.agg is None]
    agg_specs = [p for p in projections if p.agg is not None]

    groups: dict[tuple, list[dict]] = {}
    group_values: dict[tuple, tuple] = {}
    for row in rows:
        raw_vals = tuple(_read_ref(p.expr, row) for p in group_keys)
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
            out[p.alias or _default_key(p)] = k
        for spec in agg_specs:
            out[spec.alias or _default_key(spec)] = _apply_agg(spec, members)
        result.append(out)
    return result


def _apply_agg(spec: Projection, rows: list[dict]) -> Any:
    if spec.agg == "COUNT" and spec.expr.var == "*":
        return len(rows)
    values: list[Any] = []
    for row in rows:
        v = _read_ref(spec.expr, row)
        if v is None:
            continue
        values.append(v)
    if spec.agg == "COUNT":
        return len(values)
    if not values:
        return None
    numeric = [_to_number(v) for v in values if _to_number(v) is not None]
    if spec.agg == "SUM":
        return sum(numeric)
    if spec.agg == "MIN":
        return min(numeric) if numeric else min(values)
    if spec.agg == "MAX":
        return max(numeric) if numeric else max(values)
    if spec.agg == "AVG":
        return (sum(numeric) / len(numeric)) if numeric else None
    raise ValueError(f"Unsupported aggregate: {spec.agg}")


def _to_number(v: Any) -> int | float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    return None


def _sort_rows(
    rows: list[dict], order_by: OrderBy, alias_map: dict[str, Any] | None = None
) -> list[dict]:
    # Multi-column ORDER BY: apply terms in reverse so Python's stable sort
    # gives the leftmost term the highest priority.
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
            return _none_safe(v)

        out.sort(key=key, reverse=reverse)
    return out


def _none_safe(v: Any) -> tuple:
    """Sort key that buckets None at the end regardless of direction."""
    return (v is None, v if v is not None else "")
