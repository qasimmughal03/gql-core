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

from graph.store import Edge, Node, PropertyGraph
from query.ast import (
    And,
    Comparison,
    Not,
    Or,
    OrderBy,
    Projection,
    Query,
    Ref,
)
from query.parser import parse
from query.planner import (
    ExpandOp,
    FilterOp,
    JoinOp,
    Plan,
    ProjectOp,
    ScanOp,
    plan as plan_query,
)


def execute(plan_obj: Plan, graph: PropertyGraph) -> list[dict]:
    rows: Iterable[dict] = [{}]
    for op in plan_obj.ops:
        rows = _dispatch(op, rows, graph)
    if not isinstance(rows, list):
        rows = list(rows)
    return rows  # type: ignore[return-value]


def run(source: str, graph: PropertyGraph) -> list[dict]:
    """Convenience: parse + plan + execute in one call."""
    return execute(plan_query(parse(source), graph), graph)


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


def _expand(op: ExpandOp, rows: Iterable[dict], graph: PropertyGraph) -> Iterator[dict]:
    for row in rows:
        src_node = row.get(op.from_var)
        if src_node is None:
            continue
        for edge_path, target in _walk(graph, src_node, op):
            if op.to_label is not None and target.label != op.to_label:
                continue
            if not _matches_inline_filters(target, op.to_inline_filters):
                continue
            new_row = dict(row)
            if op.to_var in new_row and new_row[op.to_var] != target:
                continue
            new_row[op.to_var] = target
            if op.edge_var:
                if not edge_path:
                    continue
                # Bind the last (and for one-hop, only) edge.
                new_row[op.edge_var] = edge_path[-1]
            if not _matches_pushed(target, op.pushed, edge_var=op.edge_var, edge=edge_path[-1] if edge_path else None):
                continue
            yield new_row


def _walk(graph: PropertyGraph, start: Node, op: ExpandOp) -> Iterator[tuple[list[Edge], Node]]:
    """Yield (edge_path, target_node) pairs for each match of the rel pattern."""
    qkind = op.quantifier[0]
    if qkind == "one":
        for edge, neighbor in _direct_neighbors(graph, start, op.edge_label, op.direction):
            yield [edge], neighbor
        return
    lo, hi = _quantifier_bounds(op.quantifier)
    yield from rpq_traverse(graph, start, op.edge_label, op.direction, lo, hi)


def rpq_traverse(
    graph: PropertyGraph,
    start: Node,
    edge_label: str | None,
    direction: str,
    lo: int,
    hi: int,
) -> Iterator[tuple[list[Edge], Node]]:
    """BFS over edges matching edge_label and direction.

    Quantifier semantics:
        '*'     → lo=0,  hi=∞      (Kleene star)
        '+'     → lo=1,  hi=∞      (one-or-more)
        '*N'    → lo=hi=N
        '*M..N' → lo=M,  hi=N
    Visited set is keyed by (node_id, depth) so paths can revisit nodes
    at deeper depths but won't loop on cycles.
    """
    queue: deque[tuple[Node, list[Edge]]] = deque([(start, [])])
    visited: set[tuple[str, int]] = set()
    while queue:
        node, path = queue.popleft()
        depth = len(path)
        if depth >= lo and node is not start:
            yield path, node
        if depth == 0 and lo == 0:
            yield path, node
        if depth >= hi:
            continue
        state = (node.id, depth)
        if state in visited:
            continue
        visited.add(state)
        for edge, neighbor in _direct_neighbors(graph, node, edge_label, direction):
            queue.append((neighbor, path + [edge]))


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
        if _eval_expr(op.expr, row):
            yield row


def _eval_expr(expr: Any, row: dict) -> bool:
    if isinstance(expr, Comparison):
        return _eval_comparison(expr, row)
    if isinstance(expr, And):
        return all(_eval_expr(c, row) for c in expr.children)
    if isinstance(expr, Or):
        return any(_eval_expr(c, row) for c in expr.children)
    if isinstance(expr, Not):
        return not _eval_expr(expr.inner, row)
    raise TypeError(f"Unknown expression: {type(expr).__name__}")


def _eval_comparison(cmp: Comparison, row: dict) -> bool:
    lhs_value = _read_ref(cmp.lhs, row)
    return _apply_op(cmp.op, lhs_value, cmp.rhs)


def _apply_op(op: str, lhs: Any, rhs: Any) -> bool:
    if lhs is None:
        return False
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
    raise ValueError(f"Unsupported operator: {op}")


def _read_ref(ref: Ref, row: dict) -> Any:
    binding = row.get(ref.var)
    if binding is None:
        return None
    if ref.prop is None:
        return binding
    if hasattr(binding, "props"):
        return binding.props.get(ref.prop)
    return None


def _matches_inline_filters(
    node: Node, filters: tuple[tuple[str, Any], ...]
) -> bool:
    if not filters:
        return True
    for prop, value in filters:
        if node.props.get(prop) != value:
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
        else:
            value = target.props.get(cmp.lhs.prop) if hasattr(target, "props") else None
        if not _apply_op(cmp.op, value, cmp.rhs):
            return False
    return True


# ── Project / aggregate / order / limit ─────────────────────────────


def _project(op: ProjectOp, rows: Iterable[dict]) -> list[dict]:
    materialized = list(rows)
    has_agg = any(p.agg is not None for p in op.projections)
    if has_agg:
        out = _aggregate(op.projections, materialized)
    else:
        out = [_project_row(op.projections, row) for row in materialized]
    if op.order_by is not None:
        out = _sort_rows(out, op.order_by)
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
        return f"{proj.agg.lower()}_{proj.expr.var}" + (
            f"_{proj.expr.prop}" if proj.expr.prop else ""
        )
    return proj.expr.prop or proj.expr.var


def _aggregate(projections: tuple[Projection, ...], rows: list[dict]) -> list[dict]:
    group_keys = [p for p in projections if p.agg is None]
    agg_specs = [p for p in projections if p.agg is not None]

    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = tuple(_read_ref(p.expr, row) for p in group_keys)
        groups.setdefault(key, []).append(row)
    if not group_keys and not groups:
        groups[()] = []

    result: list[dict] = []
    for key, members in groups.items():
        out: dict = {}
        for p, k in zip(group_keys, key):
            out[p.alias or _default_key(p)] = k
        for spec in agg_specs:
            out[spec.alias or _default_key(spec)] = _apply_agg(spec, members)
        result.append(out)
    return result


def _apply_agg(spec: Projection, rows: list[dict]) -> Any:
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


def _sort_rows(rows: list[dict], order_by: OrderBy) -> list[dict]:
    var = order_by.ref.var
    prop = order_by.ref.prop
    reverse = order_by.direction.upper() == "DESC"

    def key(row: dict) -> Any:
        if var in row and not isinstance(row[var], (Node, Edge)):
            return _none_safe(row[var])
        if prop is None:
            return _none_safe(row.get(var))
        b = row.get(var)
        if hasattr(b, "props"):
            return _none_safe(b.props.get(prop))
        return _none_safe(row.get(prop))

    return sorted(rows, key=key, reverse=reverse)


def _none_safe(v: Any) -> tuple:
    """Sort key that buckets None at the end regardless of direction."""
    return (v is None, v if v is not None else "")
