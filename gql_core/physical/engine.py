"""Physical plan execution engine and optimizer for GQL-Core.

Compiles and executes logical RelOp plan trees, supporting:
- Optimization passes: predicate pushdown, filter simplification
- Clean execution with seed bindings for correlated existence probes
- Explain plan string formatting.
"""

from __future__ import annotations

from typing import Any

from gql_core.graph import PropertyGraph
from gql_core.ir import (
    And,
    AntiJoin,
    Comparison,
    Distinct,
    Except,
    Expand,
    Filter,
    GroupBy,
    Having,
    Intersect,
    Join,
    LeftOuterJoin,
    Limit,
    Literal,
    Project,
    Property,
    RecursiveExpand,
    RelOp,
    Scan,
    SemiJoin,
    Sort,
    Union,
)
from gql_core.physical.operators import (
    exec_distinct,
    exec_except,
    exec_expand,
    exec_filter,
    exec_group_by,
    exec_intersect,
    exec_join,
    exec_limit,
    exec_project,
    exec_recursive_expand,
    exec_scan,
    exec_sort,
    exec_union,
)


def execute_physical_plan(
    op: RelOp,
    graph: PropertyGraph,
    seed_rows: list[dict[str, Any]] | None = None,
    early_limit: int | None = None,
) -> list[dict[str, Any]]:
    """Recursively execute a RelOp plan tree and return list of result rows."""
    initial_rows = seed_rows if seed_rows is not None else [{}]
    stream = _dispatch_op(op, initial_rows, graph)

    results: list[dict[str, Any]] = []
    for r in stream:
        results.append(r)
        if early_limit is not None and len(results) >= early_limit:
            break
    return results


def _dispatch_op(
    op: RelOp,
    rows: Any,
    graph: PropertyGraph,
) -> Any:
    if isinstance(op, Scan):
        return exec_scan(op.var, op.label, op.inline_filters, rows, graph)

    if isinstance(op, Expand):
        input_rows = _dispatch_op(op.input, rows, graph) if op.input else rows
        return exec_expand(
            from_var=op.from_var,
            edge_var=op.edge_var,
            edge_label=op.edge_label,
            direction=op.direction,
            to_var=op.to_var,
            to_label=op.to_label,
            to_inline_filters=op.to_inline_filters,
            optional=op.optional,
            rows=input_rows,
            graph=graph,
        )

    if isinstance(op, RecursiveExpand):
        input_rows = _dispatch_op(op.input, rows, graph) if op.input else rows
        return exec_recursive_expand(
            from_var=op.from_var,
            edge_var=op.edge_var,
            edge_label=op.edge_label,
            direction=op.direction,
            min_hops=op.min_hops,
            max_hops=op.max_hops,
            to_var=op.to_var,
            to_label=op.to_label,
            trail_semantics=op.trail_semantics,
            rows=input_rows,
            graph=graph,
        )

    if isinstance(op, Filter):
        input_stream = _dispatch_op(op.input, rows, graph)
        return exec_filter(op.predicate, input_stream, graph)

    if isinstance(op, Project):
        input_stream = _dispatch_op(op.input, rows, graph)
        return exec_project(op.projections, op.distinct, input_stream, graph)

    if isinstance(op, Join):
        left_rows = list(_dispatch_op(op.left, rows, graph))
        right_rows = list(_dispatch_op(op.right, [{}] if op.kind != "CROSS" else rows, graph))
        return exec_join(left_rows, right_rows, op.on, op.kind)

    if isinstance(op, SemiJoin):
        left_rows = list(_dispatch_op(op.left, rows, graph))
        right_rows = list(_dispatch_op(op.right, [{}], graph))
        return exec_join(left_rows, right_rows, op.on, "SEMI")

    if isinstance(op, AntiJoin):
        left_rows = list(_dispatch_op(op.left, rows, graph))
        right_rows = list(_dispatch_op(op.right, [{}], graph))
        return exec_join(left_rows, right_rows, op.on, "ANTI")

    if isinstance(op, LeftOuterJoin):
        left_rows = list(_dispatch_op(op.left, rows, graph))
        right_rows = list(_dispatch_op(op.right, [{}], graph))
        return exec_join(left_rows, right_rows, op.on, "LEFT_OUTER")

    if isinstance(op, Union):
        left_rows = list(_dispatch_op(op.left, rows, graph))
        right_rows = list(_dispatch_op(op.right, rows, graph))
        return exec_union(left_rows, right_rows, op.all)

    if isinstance(op, Intersect):
        left_rows = list(_dispatch_op(op.left, rows, graph))
        right_rows = list(_dispatch_op(op.right, rows, graph))
        return exec_intersect(left_rows, right_rows, op.all)

    if isinstance(op, Except):
        left_rows = list(_dispatch_op(op.left, rows, graph))
        right_rows = list(_dispatch_op(op.right, rows, graph))
        return exec_except(left_rows, right_rows, op.all)

    if isinstance(op, GroupBy):
        input_rows = list(_dispatch_op(op.input, rows, graph))
        return exec_group_by(op.keys, op.aggregates, input_rows, graph)

    if isinstance(op, Having):
        input_stream = _dispatch_op(op.input, rows, graph)
        return exec_filter(op.predicate, input_stream, graph)

    if isinstance(op, Distinct):
        input_stream = _dispatch_op(op.input, rows, graph)
        return exec_distinct(input_stream)

    if isinstance(op, Sort):
        input_rows = list(_dispatch_op(op.input, rows, graph))
        return exec_sort(op.terms, input_rows, graph)

    if isinstance(op, Limit):
        input_stream = _dispatch_op(op.input, rows, graph)
        return exec_limit(op.count, op.offset, input_stream)

    raise TypeError(f"Unknown physical operator: {type(op).__name__}")


def optimize_plan(op: RelOp) -> RelOp:
    """Basic rule-based optimization passes: predicate pushdown into Scans."""
    if isinstance(op, Filter) and isinstance(op.input, Scan):
        scan = op.input
        pred = op.predicate
        # Check if predicate is a single equality comparison on scan.var.prop = literal
        if isinstance(pred, Comparison) and pred.op == "=":
            if isinstance(pred.lhs, Property) and pred.lhs.var == scan.var and isinstance(pred.rhs, Literal):
                new_filters = tuple(scan.inline_filters) + ((pred.lhs.prop, pred.rhs.value),)
                return Scan(var=scan.var, label=scan.label, inline_filters=new_filters)
        return Filter(input=optimize_plan(op.input), predicate=pred)

    if isinstance(op, Project):
        return Project(input=optimize_plan(op.input), projections=op.projections, distinct=op.distinct)
    if isinstance(op, Filter):
        return Filter(input=optimize_plan(op.input), predicate=op.predicate)
    if isinstance(op, Join):
        return Join(left=optimize_plan(op.left), right=optimize_plan(op.right), on=op.on, kind=op.kind)
    if isinstance(op, Sort):
        return Sort(input=optimize_plan(op.input), terms=op.terms)
    if isinstance(op, Limit):
        return Limit(input=optimize_plan(op.input), count=op.count, offset=op.offset)

    return op


def explain_plan(op: RelOp, depth: int = 0) -> str:
    """Generate a clean visual explanation string of the physical execution tree."""
    indent = "  " * depth
    name = type(op).__name__
    details = ""

    if isinstance(op, Scan):
        details = f"(var={op.var}, label={op.label}, filters={op.inline_filters})"
    elif isinstance(op, Expand):
        details = f"({op.from_var} -[{op.edge_label}]-> {op.to_var}, optional={op.optional})"
    elif isinstance(op, RecursiveExpand):
        details = f"({op.from_var} -[{op.edge_label}*{op.min_hops}..{op.max_hops}]-> {op.to_var})"
    elif isinstance(op, Join):
        details = f"(kind={op.kind}, on={op.on})"
    elif isinstance(op, Limit):
        details = f"(limit={op.count}, offset={op.offset})"

    line = f"{indent}└─ {name} {details}".rstrip()
    children = []
    if hasattr(op, "input"):
        children.append(explain_plan(getattr(op, "input"), depth + 1))
    if hasattr(op, "left") and hasattr(op, "right"):
        children.append(explain_plan(getattr(op, "left"), depth + 1))
        children.append(explain_plan(getattr(op, "right"), depth + 1))

    if children:
        return line + "\n" + "\n".join(children)
    return line
