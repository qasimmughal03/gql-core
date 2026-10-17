"""Logical planning for GQL-Core queries.

Translates a Query AST into a list of Ops (Scan / Expand / Filter / Project)
with simple predicate pushdown:

    1. Pick the seed node variable (smallest expected scan).
    2. Walk each pattern; emit Scan for the seed, Expand for each (rel, node).
    3. For multi-pattern queries, additional patterns are executed and joined
       on shared variables via a Join op.
    4. Comparisons that reference only a single variable are pushed into that
       variable's Scan; the rest land in a trailing Filter.
    5. Project ends the plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gql_core.graph import PropertyGraph
from gql_core.query.ast import (
    And,
    Comparison,
    Expr,
    Not,
    NodePat,
    Or,
    Pattern,
    Projection,
    Query,
    Ref,
    RelPat,
)


@dataclass
class ScanOp:
    var: str
    label: str | None
    inline_filters: tuple[tuple[str, Any], ...]      # (prop, value) equality
    pushed: list[Comparison] = field(default_factory=list)


@dataclass
class ExpandOp:
    from_var: str
    edge_var: str | None
    edge_label: str | None
    direction: str
    quantifier: tuple
    to_var: str
    to_label: str | None
    to_inline_filters: tuple[tuple[str, Any], ...]
    pushed: list[Comparison] = field(default_factory=list)


@dataclass
class JoinOp:
    """Joins rows from a second pattern onto rows from the first via shared variables."""
    on_vars: tuple[str, ...]
    rhs_ops: list


@dataclass
class FilterOp:
    expr: Expr


@dataclass
class ProjectOp:
    projections: tuple[Projection, ...]
    order_by: Any
    limit: int | None


@dataclass
class Plan:
    ops: list


def plan(query: Query, graph: PropertyGraph | None = None) -> Plan:
    if not query.patterns:
        raise ValueError("Query has no patterns")

    pattern_to_ops: list[list] = []
    pattern_vars: list[set[str]] = []
    for pat in query.patterns:
        ops, vars_ = _ops_for_pattern(pat)
        pattern_to_ops.append(ops)
        pattern_vars.append(vars_)

    final_ops: list = list(pattern_to_ops[0])
    seen_vars: set[str] = set(pattern_vars[0])
    for ops, vars_ in zip(pattern_to_ops[1:], pattern_vars[1:]):
        shared = tuple(sorted(seen_vars & vars_))
        final_ops.append(JoinOp(on_vars=shared, rhs_ops=ops))
        seen_vars |= vars_

    if query.where is not None:
        push_targets = _scan_targets(final_ops)
        residual = _push_predicates(query.where, push_targets)
        if residual is not None:
            final_ops.append(FilterOp(expr=residual))

    final_ops.append(
        ProjectOp(
            projections=query.projections,
            order_by=query.order_by,
            limit=query.limit,
        )
    )
    return Plan(ops=final_ops)


# ── Helpers ─────────────────────────────────────────────────────────


def _ops_for_pattern(pattern: Pattern) -> tuple[list, set[str]]:
    if not pattern.nodes:
        return [], set()
    head = pattern.nodes[0]
    ops: list = [
        ScanOp(
            var=head.var,
            label=head.label,
            inline_filters=tuple(head.filters),
        )
    ]
    seen: set[str] = {head.var}
    prev_var = head.var
    for rel, node in zip(pattern.rels, pattern.nodes[1:]):
        ops.append(
            ExpandOp(
                from_var=prev_var,
                edge_var=rel.var,
                edge_label=rel.label,
                direction=rel.direction,
                quantifier=rel.quantifier,
                to_var=node.var,
                to_label=node.label,
                to_inline_filters=tuple(node.filters),
            )
        )
        seen.add(node.var)
        if rel.var:
            seen.add(rel.var)
        prev_var = node.var
    return ops, seen


def _scan_targets(ops: list) -> dict[str, list]:
    """Map var → list of ops that produce that var (for predicate pushdown)."""
    targets: dict[str, list] = {}
    for op in ops:
        if isinstance(op, ScanOp):
            targets.setdefault(op.var, []).append(op)
        elif isinstance(op, ExpandOp):
            targets.setdefault(op.to_var, []).append(op)
            if op.edge_var:
                targets.setdefault(op.edge_var, []).append(op)
    return targets


def _push_predicates(expr: Expr, targets: dict[str, list]) -> Expr | None:
    """Walk the expression; push single-var comparisons into their scan/expand op.

    Returns a residual expression with the pushed comparisons stripped, or None
    if everything was pushed.
    """
    return _split(expr, targets)


def _vars_in(expr: Expr) -> set[str]:
    if isinstance(expr, Comparison):
        return {expr.lhs.var}
    if isinstance(expr, Not):
        return _vars_in(expr.inner)
    if isinstance(expr, (And, Or)):
        out: set[str] = set()
        for c in expr.children:
            out |= _vars_in(c)
        return out
    return set()


def _split(expr: Expr, targets: dict[str, list]) -> Expr | None:
    if isinstance(expr, And):
        residuals = []
        for child in expr.children:
            r = _split(child, targets)
            if r is not None:
                residuals.append(r)
        if not residuals:
            return None
        if len(residuals) == 1:
            return residuals[0]
        return And(children=tuple(residuals))
    if isinstance(expr, Comparison):
        single = expr.lhs.var
        ops = targets.get(single)
        if ops:
            ops[0].pushed.append(expr)
            return None
        return expr
    # Or, Not, and any non-trivially-decomposable expression: don't split,
    # leave for the trailing FilterOp.
    return expr
