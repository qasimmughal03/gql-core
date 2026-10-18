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


@dataclass(frozen=True)
class RelPat:
    var: str | None
    label: str | None
    direction: str
    quantifier: tuple


@dataclass(frozen=True)
class Pattern:
    nodes: tuple[NodePat, ...]
    rels: tuple[RelPat, ...]   # len(rels) == len(nodes) - 1


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


# Type alias for any boolean expression.
Expr = Comparison | And | Or | Not


@dataclass(frozen=True)
class Projection:
    expr: Ref
    agg: str | None        # 'COUNT' | 'SUM' | 'AVG' | 'MIN' | 'MAX' | None
    alias: str | None


@dataclass(frozen=True)
class OrderTerm:
    ref: Ref
    direction: str         # 'ASC' or 'DESC'


@dataclass(frozen=True)
class OrderBy:
    terms: tuple[OrderTerm, ...]


@dataclass(frozen=True)
class Query:
    patterns: tuple[Pattern, ...]
    where: Expr | None
    projections: tuple[Projection, ...]
    order_by: OrderBy | None
    limit: int | None
    distinct: bool = False
