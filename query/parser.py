"""GQL-Core source → Query AST.

Wraps the Lark parser. The transformer collapses the parse tree into
the frozen dataclasses defined in `query.ast`. Use parse(src) for the
AST or parse_tree(src) for a Lark pretty-print (handy for the README).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lark import Lark, Token, Transformer, v_args

from query.ast import (
    And,
    Comparison,
    Not,
    NodePat,
    Or,
    OrderBy,
    OrderTerm,
    Pattern,
    Projection,
    Query,
    Ref,
    RelPat,
)

_GRAMMAR = Path(__file__).resolve().parent / "grammar.lark"


class _ToAST(Transformer):
    def __init__(self) -> None:
        super().__init__()
        self._anon_counter = 0

    # ── Values ────────────────────────────────────────────────────
    def str_val(self, items):
        # ESCAPED_STRING contains surrounding quotes — strip them.
        return items[0][1:-1]

    def single_str_val(self, items):
        raw = items[0][1:-1]
        return raw.replace("\\'", "'").replace("\\\\", "\\")

    def num_val(self, items):
        text = items[0]
        if "." in text or "e" in text or "E" in text:
            return float(text)
        return int(text)

    def true_val(self, _items):
        return True

    def false_val(self, _items):
        return False

    def null_val(self, _items):
        return None

    def value(self, items):
        return items[0]

    # ── Refs / aliases ────────────────────────────────────────────
    def ref(self, items):
        if len(items) == 1:
            return Ref(var=str(items[0]), prop=None)
        return Ref(var=str(items[0]), prop=str(items[1]))

    def alias(self, items):
        return str(items[0])

    # ── Node + edge patterns ──────────────────────────────────────
    def prop_filter(self, items):
        return (str(items[0]), items[1])

    def prop_filter_block(self, items):
        return tuple(items)

    def node_var(self, items):
        return ("var", str(items[0]))

    def node_pat(self, items):
        var: str | None = None
        label: str | None = None
        filters: tuple = ()
        for child in items:
            if isinstance(child, tuple) and child and child[0] == "var":
                var = child[1]
            elif isinstance(child, Token) and child.type == "LABEL":
                label = str(child)
            elif isinstance(child, tuple):
                filters = child
        if var is None:
            self._anon_counter += 1
            var = f"__anon_{self._anon_counter}"
        return NodePat(var=var, label=label, filters=filters)

    def edge_var(self, items):
        return ("var", str(items[0]))

    def edge_label(self, items):
        return ("label", str(items[0]))

    def q_star(self, _items):
        return ("star", None)

    def q_plus(self, _items):
        return ("plus",)

    def q_exactly(self, items):
        return ("exactly", int(items[0]))

    def q_range(self, items):
        return ("range", int(items[0]), int(items[1]))

    def _build_rel(self, items, direction: str) -> RelPat:
        var: str | None = None
        label: str | None = None
        quantifier: tuple = ("one",)
        for child in items:
            if isinstance(child, tuple):
                if child[0] == "var":
                    var = child[1]
                elif child[0] == "label":
                    label = child[1]
                else:
                    quantifier = child
        return RelPat(var=var, label=label, direction=direction, quantifier=quantifier)

    def rel_out(self, items):
        return self._build_rel(items, "out")

    def rel_in(self, items):
        return self._build_rel(items, "in")

    def rel_undirected(self, items):
        return self._build_rel(items, "undirected")

    def rel_out_anon(self, _items):
        return RelPat(var=None, label=None, direction="out", quantifier=("one",))

    def rel_in_anon(self, _items):
        return RelPat(var=None, label=None, direction="in", quantifier=("one",))

    def rel_undirected_anon(self, _items):
        return RelPat(var=None, label=None, direction="undirected", quantifier=("one",))

    def pattern(self, items):
        nodes: list[NodePat] = []
        rels: list[RelPat] = []
        for child in items:
            if isinstance(child, NodePat):
                nodes.append(child)
            elif isinstance(child, RelPat):
                rels.append(child)
        return Pattern(nodes=tuple(nodes), rels=tuple(rels))

    def match_clause(self, items):
        return tuple(items)

    # ── WHERE ─────────────────────────────────────────────────────
    @v_args(inline=True)
    def comparison(self, ref, op_token, value):
        return Comparison(lhs=ref, op=str(op_token), rhs=value)

    def negate(self, items):
        return Not(inner=items[0])

    def atom_expr(self, items):
        return items[0]

    def not_expr(self, items):
        return items[0]

    def and_expr(self, items):
        if len(items) == 1:
            return items[0]
        return And(children=tuple(items))

    def or_expr(self, items):
        if len(items) == 1:
            return items[0]
        return Or(children=tuple(items))

    def where_clause(self, items):
        return items[0]

    # ── RETURN ────────────────────────────────────────────────────
    def agg_call(self, items):
        agg_name = str(items[0]).upper()
        arg = items[1]
        if isinstance(arg, Token) and arg.type == "STAR":
            ref = Ref(var="*", prop=None)
        else:
            ref = arg
        return (agg_name, ref)

    def proj_ref(self, items):
        ref = items[0]
        alias_value = str(items[1]) if len(items) > 1 else None
        return Projection(expr=ref, agg=None, alias=alias_value)

    def proj_agg(self, items):
        agg_name, ref = items[0]
        alias_value = str(items[1]) if len(items) > 1 else None
        return Projection(expr=ref, agg=agg_name, alias=alias_value)

    def direction(self, items):
        return str(items[0])

    def order_term(self, items):
        ref = items[0]
        direction = items[1] if len(items) > 1 else "ASC"
        return OrderTerm(ref=ref, direction=direction)

    def order_by(self, items):
        return OrderBy(terms=tuple(items))

    def limit(self, items):
        return int(items[0])

    def return_clause(self, items):
        projections: list[Projection] = []
        order: OrderBy | None = None
        lim: int | None = None
        for child in items:
            if isinstance(child, Projection):
                projections.append(child)
            elif isinstance(child, OrderBy):
                order = child
            elif isinstance(child, int):
                lim = child
        return projections, order, lim

    # ── Top level ─────────────────────────────────────────────────
    def query(self, items):
        patterns = items[0]
        where: Any = None
        projections: tuple[Projection, ...]
        order: OrderBy | None
        lim: int | None
        # Items: [match_clause, optional where, return_clause]
        if len(items) == 3:
            where = items[1]
            ret = items[2]
        else:
            ret = items[1]
        projections, order, lim = ret
        return Query(
            patterns=tuple(patterns),
            where=where,
            projections=tuple(projections),
            order_by=order,
            limit=lim,
        )

    def start(self, items):
        return items[0]


# Singleton parsers — Lark startup is the slow bit, so we pay it once.
_PARSER_LALR = Lark.open(str(_GRAMMAR), parser="lalr", maybe_placeholders=False)
_PARSER_AST = Lark.open(
    str(_GRAMMAR), parser="lalr", maybe_placeholders=False, transformer=_ToAST()
)


def parse(source: str) -> Query:
    """Parse a GQL-Core source string into a Query AST."""
    return _PARSER_AST.parse(source)


def parse_tree(source: str) -> str:
    """Return Lark's pretty-printed parse tree (no transformer)."""
    return _PARSER_LALR.parse(source).pretty()
