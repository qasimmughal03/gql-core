"""Physical execution operators for GQL-Core.

Implements iterator-based physical operators:
- Scan, Expand (with OPTIONAL match), RecursiveExpand (trail semantics)
- Filter (3VL Kleene logic), Project, Sort, Distinct, Limit
- Relational joins: Inner, Left Outer, Semi, Anti, Cross
- Set algebra: Union, Union All, Intersect, Intersect All, Except, Except All
- Aggregation: GroupBy, Having, COUNT, SUM, AVG, MIN, MAX, COLLECT (with DISTINCT)
"""

from __future__ import annotations

import collections
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Iterator
from typing import Any

from gql_core.graph import Edge, Node, PropertyGraph
from gql_core.ir import (
    AggregateExpr,
    BoolExpr,
    ProjectItem,
    SortTerm,
    ValueExpr,
)
from gql_core.physical.evaluator import eval_predicate, eval_value


def _normalize_key(val: Any) -> Any:
    """Ensure group-by and distinct keys are hashable."""
    if isinstance(val, (list, tuple)):
        return tuple(_normalize_key(x) for x in val)
    if isinstance(val, dict):
        return tuple(sorted((k, _normalize_key(v)) for k, v in val.items()))
    return val


def _row_to_key(row: dict[str, Any], keys: tuple[str, ...]) -> tuple:
    return tuple(_normalize_key(row.get(k)) for k in keys)


def _row_signature(row: dict[str, Any]) -> tuple:
    return tuple(sorted((k, _normalize_key(v)) for k, v in row.items()))


# ═══════════════════════════════════════════════════════════════════════
# PHYSICAL OPERATOR EXECUTORS
# ═══════════════════════════════════════════════════════════════════════


def exec_scan(
    var: str,
    label: str | None,
    inline_filters: tuple[tuple[str, Any], ...],
    rows: Iterable[dict[str, Any]],
    graph: PropertyGraph,
) -> Iterator[dict[str, Any]]:
    """Scan nodes by label or all, applying inline equality filters."""
    if label is not None:
        nodes = graph.nodes_by_label(label)
    else:
        nodes = (n for n in graph._nodes.values())

    matched_nodes = []
    for n in nodes:
        matches = True
        for prop, expected in inline_filters:
            if n.props.get(prop) != expected:
                matches = False
                break
        if matches:
            matched_nodes.append(n)

    for r in rows:
        for node in matched_nodes:
            new_r = dict(r)
            new_r[var] = node
            yield new_r


def exec_expand(
    from_var: str,
    edge_var: str | None,
    edge_label: str | None,
    direction: str,
    to_var: str,
    to_label: str | None,
    to_inline_filters: tuple[tuple[str, Any], ...],
    optional: bool,
    rows: Iterable[dict[str, Any]],
    graph: PropertyGraph,
) -> Iterator[dict[str, Any]]:
    """Traverse relationships incident to from_var."""
    for r in rows:
        src_entity = r.get(from_var)
        if src_entity is None:
            if optional:
                out = dict(r)
                if to_var:
                    out[to_var] = None
                if edge_var:
                    out[edge_var] = None
                yield out
            continue

        src_id = getattr(src_entity, "id", src_entity)
        edges = []
        if direction in ("out", "undirected"):
            edges.extend(graph.outgoing(src_id, edge_label))
        if direction in ("in", "undirected"):
            edges.extend(graph.incoming(src_id, edge_label))

        match_count = 0
        for e in edges:
            nbr_id = e.dst if e.src == src_id else e.src
            nbr_node = graph.get_node(nbr_id)
            if nbr_node is None:
                continue
            if to_label and nbr_node.label != to_label:
                continue

            matches_filters = True
            for p, expected in to_inline_filters:
                if nbr_node.props.get(p) != expected:
                    matches_filters = False
                    break
            if not matches_filters:
                continue

            match_count += 1
            out = dict(r)
            if to_var:
                out[to_var] = nbr_node
            if edge_var:
                out[edge_var] = e
            yield out

        # OPTIONAL MATCH fallback: retain row with None bindings if no match
        if match_count == 0 and optional:
            out = dict(r)
            if to_var:
                out[to_var] = None
            if edge_var:
                out[edge_var] = None
            yield out


def exec_recursive_expand(
    from_var: str,
    edge_var: str | None,
    edge_label: str | None,
    direction: str,
    min_hops: int,
    max_hops: int | None,
    to_var: str,
    to_label: str | None,
    trail_semantics: bool,
    rows: Iterable[dict[str, Any]],
    graph: PropertyGraph,
) -> Iterator[dict[str, Any]]:
    """Recursive RPQ expansion using BFS and relationship trail semantics."""
    for r in rows:
        src_entity = r.get(from_var)
        if src_entity is None:
            continue
        src_id = getattr(src_entity, "id", src_entity)
        src_node = graph.get_node(src_id)
        if src_node is None:
            continue

        # Zero hops: yields start node if min_hops == 0
        if min_hops == 0 and (to_label is None or src_node.label == to_label):
            out = dict(r)
            out[to_var] = src_node
            if edge_var:
                out[edge_var] = None
            yield out

        # Queue: (current_node, depth, used_edges: frozenset[edge_id])
        queue: deque[tuple[Node, int, frozenset[str]]] = deque([(src_node, 0, frozenset())])

        while queue:
            curr, depth, used = queue.popleft()
            if max_hops is not None and depth >= max_hops:
                continue

            edges = []
            if direction in ("out", "undirected"):
                edges.extend(graph.outgoing(curr.id, edge_label))
            if direction in ("in", "undirected"):
                edges.extend(graph.incoming(curr.id, edge_label))

            for e in edges:
                if trail_semantics and e.id in used:
                    continue  # Trail isomorphism: each relationship instance used at most once per path

                nbr_id = e.dst if e.src == curr.id else e.src
                nbr_node = graph.get_node(nbr_id)
                if nbr_node is None:
                    continue

                new_depth = depth + 1
                new_used = used | {e.id}

                if new_depth >= min_hops and (to_label is None or nbr_node.label == to_label):
                    out = dict(r)
                    out[to_var] = nbr_node
                    if edge_var:
                        out[edge_var] = e
                    yield out

                if max_hops is None or new_depth < max_hops:
                    queue.append((nbr_node, new_depth, new_used))


def exec_filter(
    predicate: BoolExpr,
    rows: Iterable[dict[str, Any]],
    graph: PropertyGraph,
) -> Iterator[dict[str, Any]]:
    """Filter rows retaining strictly those where predicate evaluates to True (3VL)."""
    for r in rows:
        if eval_predicate(predicate, r, graph) is True:
            yield r


def exec_project(
    projections: tuple[ProjectItem, ...],
    distinct: bool,
    rows: Iterable[dict[str, Any]],
    graph: PropertyGraph,
) -> Iterator[dict[str, Any]]:
    """Project expressions to aliases and optionally deduplicate."""
    seen = set() if distinct else None
    for r in rows:
        out: dict[str, Any] = {}
        for p in projections:
            out[p.alias] = eval_value(p.expr, r, graph)
        if distinct:
            sig = _row_signature(out)
            if sig in seen:
                continue
            seen.add(sig)
        yield out


def exec_join(
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    on: tuple[str, ...],
    kind: str,
) -> Iterator[dict[str, Any]]:
    """Execute relational joins: INNER, LEFT_OUTER, SEMI, ANTI, CROSS."""
    if kind == "CROSS":
        for l in left_rows:
            for r in right_rows:
                yield {**l, **r}
        return

    # Build hash index on right rows
    right_index = defaultdict(list)
    for r in right_rows:
        key = _row_to_key(r, on)
        right_index[key].append(r)

    if kind == "INNER":
        for l in left_rows:
            key = _row_to_key(l, on)
            for r in right_index.get(key, []):
                yield {**l, **r}

    elif kind == "LEFT_OUTER":
        right_keys_all = set()
        for r in right_rows:
            right_keys_all.update(r.keys())

        for l in left_rows:
            key = _row_to_key(l, on)
            matches = right_index.get(key, [])
            if matches:
                for r in matches:
                    yield {**l, **r}
            else:
                # Pad unmatched right columns with None
                padded = dict(l)
                for rk in right_keys_all:
                    if rk not in padded:
                        padded[rk] = None
                yield padded

    elif kind == "SEMI":
        for l in left_rows:
            key = _row_to_key(l, on)
            if key in right_index and len(right_index[key]) > 0:
                yield l

    elif kind == "ANTI":
        for l in left_rows:
            key = _row_to_key(l, on)
            if key not in right_index or len(right_index[key]) == 0:
                yield l


def exec_union(
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    all: bool,
) -> Iterator[dict[str, Any]]:
    """Execute UNION (distinct) or UNION ALL (multiset)."""
    if all:
        yield from left_rows
        yield from right_rows
    else:
        seen = set()
        for r in left_rows:
            sig = _row_signature(r)
            if sig not in seen:
                seen.add(sig)
                yield r
        for r in right_rows:
            sig = _row_signature(r)
            if sig not in seen:
                seen.add(sig)
                yield r


def exec_intersect(
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    all: bool,
) -> Iterator[dict[str, Any]]:
    """Execute INTERSECT (distinct) or INTERSECT ALL (multiset)."""
    if all:
        right_counter: Counter[tuple] = Counter(_row_signature(r) for r in right_rows)
        for l in left_rows:
            sig = _row_signature(l)
            if right_counter[sig] > 0:
                right_counter[sig] -= 1
                yield l
    else:
        right_set = {_row_signature(r) for r in right_rows}
        seen = set()
        for l in left_rows:
            sig = _row_signature(l)
            if sig in right_set and sig not in seen:
                seen.add(sig)
                yield l


def exec_except(
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    all: bool,
) -> Iterator[dict[str, Any]]:
    """Execute EXCEPT (distinct) or EXCEPT ALL (multiset)."""
    if all:
        right_counter: Counter[tuple] = Counter(_row_signature(r) for r in right_rows)
        for l in left_rows:
            sig = _row_signature(l)
            if right_counter[sig] > 0:
                right_counter[sig] -= 1
            else:
                yield l
    else:
        right_set = {_row_signature(r) for r in right_rows}
        seen = set()
        for l in left_rows:
            sig = _row_signature(l)
            if sig not in right_set and sig not in seen:
                seen.add(sig)
                yield l


def exec_group_by(
    keys: tuple[str, ...],
    aggregates: tuple[ProjectItem, ...],
    rows: list[dict[str, Any]],
    graph: PropertyGraph,
) -> Iterator[dict[str, Any]]:
    """Group rows by keys and compute aggregate functions."""
    groups = defaultdict(list)
    for r in rows:
        key = _row_to_key(r, keys)
        groups[key].append(r)

    # Empty rows handling for global aggregation (keys is empty)
    if not rows and not keys and aggregates:
        out: dict[str, Any] = {}
        for agg_item in aggregates:
            out[agg_item.alias] = _compute_aggregate(agg_item.expr, [], graph)
        yield out
        return

    for key_tuple, group_rows in groups.items():
        out = {}
        for k_name, val in zip(keys, key_tuple):
            out[k_name] = val
        for agg_item in aggregates:
            out[agg_item.alias] = _compute_aggregate(agg_item.expr, group_rows, graph)
        yield out


def _compute_aggregate(expr: ValueExpr, group_rows: list[dict[str, Any]], graph: PropertyGraph) -> Any:
    if not isinstance(expr, AggregateExpr):
        # Non-aggregate expression evaluated on first row
        return eval_value(expr, group_rows[0], graph) if group_rows else None

    func = expr.func.upper()

    # COUNT(*)
    if expr.expr is None:
        if func == "COUNT":
            return len(group_rows)
        return None

    # Evaluate inner expression for all rows in group
    vals = [eval_value(expr.expr, r, graph) for r in group_rows]
    non_null_vals = [v for v in vals if v is not None]

    if expr.distinct:
        # Deduplicate non-null values preserving order
        seen = set()
        dist_vals = []
        for v in non_null_vals:
            nv = _normalize_key(v)
            if nv not in seen:
                seen.add(nv)
                dist_vals.append(v)
        non_null_vals = dist_vals

    if func == "COUNT":
        return len(non_null_vals)

    if not non_null_vals:
        return None  # SUM, AVG, MIN, MAX over empty set is null

    if func == "SUM":
        return sum(non_null_vals)
    if func == "AVG":
        return sum(non_null_vals) / len(non_null_vals)
    if func == "MIN":
        return min(non_null_vals)
    if func == "MAX":
        return max(non_null_vals)
    if func == "COLLECT":
        return non_null_vals

    return None


def exec_sort(
    terms: tuple[SortTerm, ...],
    rows: list[dict[str, Any]],
    graph: PropertyGraph,
) -> list[dict[str, Any]]:
    """Sort rows by terms (ASC/DESC), placing nulls last deterministically."""
    if not terms:
        return rows

    def _sort_key(row: dict[str, Any]) -> tuple:
        k = []
        for t in terms:
            v = eval_value(t.expr, row, graph)
            is_null = v is None
            rev = (t.direction.upper() == "DESC")
            # Nulls last: in ASC, null flag 1 puts it last. In DESC, null flag 1 puts it last if inverted
            k.append((is_null, v if not is_null else 0))
        return tuple(k)

    # For reverse per column, Python list.sort with custom comparator or tuple
    # Simplest deterministic multi-column sort:
    res = list(rows)
    for t in reversed(terms):
        rev = (t.direction.upper() == "DESC")
        res.sort(
            key=lambda r: (eval_value(t.expr, r, graph) is None, eval_value(t.expr, r, graph) or 0),
            reverse=rev,
        )
    return res


def exec_distinct(rows: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    seen = set()
    for r in rows:
        sig = _row_signature(r)
        if sig not in seen:
            seen.add(sig)
            yield r


def exec_limit(count: int, offset: int, rows: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    idx = 0
    yielded = 0
    for r in rows:
        if idx >= offset:
            yield r
            yielded += 1
            if yielded >= count:
                break
        idx += 1
