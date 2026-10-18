"""Abstract syntax tree for GQL-Core queries.

Frozen dataclasses produced by the Lark transformer in `query.parser`.
Direction values: 'out' | 'in' | 'undirected'.
Quantifier shape: ('one',) | ('plus',) | ('star', None) | ('exactly', n)
                  | ('range', lo, hi). The 'one' form is implicit when no
                  quantifier appears in the source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NodePat:
    var: str
    label: str | None
    filters: tuple[tuple[str, Any], ...] = ()
    labels: tuple[str, ...] = ()
    has_map: bool = False


@dataclass(frozen=True)
class RelPat:
    var: str | None
    label: str | None
    direction: str
    quantifier: tuple
    filters: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class Pattern:
    nodes: tuple[NodePat, ...]
    rels: tuple[RelPat, ...]   # len(rels) == len(nodes) - 1
    path_var: str | None = None


@dataclass(frozen=True)
class Ref:
    """A path expression: var (.prop)? — prop may be None for the whole binding."""
    var: str
    prop: str | None = None


@dataclass(frozen=True)
class Comparison:
    lhs: Ref
    op: str
    rhs: Any


@dataclass(frozen=True)
class And:
    children: tuple


@dataclass(frozen=True)
class Or:
    children: tuple


@dataclass(frozen=True)
class Not:
    inner: Any


@dataclass(frozen=True)
class PatternPredicate:
    pattern: Pattern


# Type alias for any boolean expression.
Expr = Comparison | And | Or | Not | PatternPredicate


@dataclass(frozen=True)
class Projection:
    expr: Ref
    agg: str | None        # 'COUNT' | 'SUM' | 'AVG' | 'MIN' | 'MAX' | None
    alias: str | None
    raw_expr: str | None = None
    distinct: bool = False


@dataclass(frozen=True)
class OrderTerm:
    ref: Ref
    direction: str         # 'ASC' or 'DESC'


@dataclass(frozen=True)
class OrderBy:
    terms: tuple[OrderTerm, ...]


@dataclass(frozen=True)
class MatchClause:
    patterns: tuple[Pattern, ...]
    where: Any | None = None
    optional: bool = False


@dataclass(frozen=True)
class UnwindClause:
    expr: Any
    alias: str


@dataclass(frozen=True)
class WithClause:
    items: tuple[Projection, ...]
    where: Any | None = None
    order_by: OrderBy | None = None
    skip: Any | None = None
    limit: Any | None = None
    distinct: bool = False


@dataclass(frozen=True)
class ReturnClause:
    items: tuple[Projection, ...]
    order_by: OrderBy | None = None
    skip: Any | None = None
    limit: Any | None = None
    distinct: bool = False


@dataclass(frozen=True)
class CreateClause:
    patterns: tuple[Pattern, ...]


@dataclass(frozen=True)
class SetItem:
    kind: str  # 'prop' | 'prop_merge' | 'labels'
    target: Any
    value: Any = None
    prop_name: str | None = None
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class SetClause:
    items: tuple[SetItem, ...]


@dataclass(frozen=True)
class DeleteClause:
    items: tuple[Any, ...]
    detach: bool = False


@dataclass(frozen=True)
class RemoveItem:
    kind: str  # 'prop' | 'labels'
    target: Any
    prop_name: str | None = None
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class RemoveClause:
    items: tuple[RemoveItem, ...]


@dataclass(frozen=True)
class MergeAction:
    on_event: str  # 'CREATE' or 'MATCH'
    items: tuple[SetItem, ...]


@dataclass(frozen=True)
class MergeClause:
    pattern: Pattern
    actions: tuple[MergeAction, ...] = ()


@dataclass(frozen=True)
class CallClause:
    proc_name: str
    args: tuple[Any, ...] = ()
    yield_items: tuple[tuple[str, str | None], ...] = ()


Clause = (
    MatchClause
    | UnwindClause
    | WithClause
    | ReturnClause
    | CreateClause
    | SetClause
    | DeleteClause
    | RemoveClause
    | MergeClause
    | CallClause
)


@dataclass(frozen=True)
class Query:
    patterns: tuple[Pattern, ...] = ()
    where: Expr | None = None
    projections: tuple[Projection, ...] = ()
    order_by: OrderBy | None = None
    limit: int | None = None
    distinct: bool = False
    unions: tuple[tuple[str, Any], ...] = ()
    clauses: tuple[Any, ...] = ()
