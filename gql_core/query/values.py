"""Ground string literals in generated Cypher to the values stored in the graph.

A model writing ``{name: "Shooting guard"}`` or ``WHERE p.name = 'Power Forward'`` cannot
know that the graph stores ``shooting guard``; the query is valid, runs, and returns
nothing. :func:`ground_values` replaces a string literal that is compared by equality
(inline property map, ``=``, ``<>``, or ``IN [...]``) with a property of a labelled
node, but only when

* no node with that label stores the literal exactly, and
* exactly one stored value of that label and property matches it after Unicode
  normalisation, case folding and whitespace collapsing.

Everything else in the query text is left unchanged. ``CONTAINS``, ``STARTS WITH``,
regexes and literals that already match are never touched.
"""

from __future__ import annotations

import re
import unicodedata
import weakref
from dataclasses import dataclass, field
from typing import Any

from lark import Token, Tree

from gql_core.graph import PropertyGraph
from gql_core.query.directions import _node_info, _parse_tree, _text


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip().casefold()


class ValueIndex:
    """Lazily built ``(label, property) -> {normalised value: {stored values}}`` index."""

    def __init__(self, graph: PropertyGraph) -> None:
        self.graph = graph
        self._exact: dict[tuple[str, str], set[str]] = {}
        self._folded: dict[tuple[str, str], dict[str, set[str]]] = {}

    def _build(self, label: str, prop: str) -> None:
        key = (label, prop)
        exact: set[str] = set()
        folded: dict[str, set[str]] = {}
        nodes = self.graph._nodes
        for nid in self.graph._by_label.get(label, ()):
            v = nodes[nid].props.get(prop)
            if isinstance(v, str):
                exact.add(v)
                folded.setdefault(_norm(v), set()).add(v)
        self._exact[key], self._folded[key] = exact, folded

    def resolve(self, labels: set[str], prop: str, value: str) -> str | None:
        """The single stored value ``value`` should be, or None to leave it alone."""
        matches: set[str] = set()
        for label in labels:
            if (label, prop) not in self._exact:
                self._build(label, prop)
            if value in self._exact[(label, prop)]:
                return None
            matches |= self._folded[(label, prop)].get(_norm(value), set())
        return next(iter(matches)) if len(matches) == 1 else None


_INDEXES: "weakref.WeakKeyDictionary[PropertyGraph, tuple[int, ValueIndex]]" = weakref.WeakKeyDictionary()


def value_index(graph: PropertyGraph) -> ValueIndex:
    """Cached per graph; rebuilt when the node count changes."""
    cached = _INDEXES.get(graph)
    if cached is None or cached[0] != len(graph._nodes):
        cached = (len(graph._nodes), ValueIndex(graph))
        _INDEXES[graph] = cached
    return cached[1]


@dataclass
class ValueGrounding:
    """Result of :func:`ground_values`."""

    query: str
    original: str
    changes: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.changes)


def _string_token(t: Any) -> Token | None:
    """The string-literal token if ``t`` is a plain string literal."""
    while isinstance(t, Tree) and len([c for c in t.children if isinstance(c, (Tree, Token))]) == 1:
        t = t.children[0]
    if isinstance(t, Tree) and t.data in ("str_val", "single_str_val"):
        t = t.children[0]
    if isinstance(t, Token) and t.type in ("ESCAPED_STRING", "SINGLE_QUOTED_STRING"):
        return t
    return None


def _decode(tok: Token) -> str:
    body = str(tok)[1:-1]
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), body)


def _encode(value: str, quote: str) -> str:
    return quote + value.replace("\\", "\\\\").replace(quote, "\\" + quote) + quote


def _prop_ref(t: Any) -> tuple[str, str] | None:
    """(variable, property) if ``t`` is ``var.prop``."""
    if isinstance(t, Tree) and t.data == "prop_op":
        base = t.children[0]
        prop = t.children[-1]
        if isinstance(base, Tree) and base.data == "var_ref":
            return _text(base), _text(prop)
    return None


def ground_values(query: str, graph: PropertyGraph, index: ValueIndex | None = None) -> ValueGrounding:
    """Replace equality-compared string literals with the stored value they denote."""
    result = ValueGrounding(query=query, original=query)
    try:
        tree = _parse_tree(query)
    except Exception:  # noqa: BLE001
        return result
    idx = index or value_index(graph)

    var_labels: dict[str, set[str]] = {}
    for np in tree.find_data("node_pat"):
        var, labels = _node_info(np)
        if var and labels:
            var_labels.setdefault(var, set()).update(labels)

    sites: list[tuple[set[str], str, Token]] = []  # (labels, property, literal token)
    for np in tree.find_data("node_pat"):
        var, labels = _node_info(np)
        labels = labels or var_labels.get(var or "", set())
        for m in (c for c in np.children if isinstance(c, Tree) and c.data == "map_lit"):
            for entry in m.find_data("map_entry"):
                key = entry.children[0]
                tok = _string_token(entry.children[-1])
                if tok is not None and labels:
                    sites.append((labels, _text(key).strip('"'), tok))
    for op in ("eq_op", "neq_op", "in_op"):
        for t in tree.find_data(op):
            operands = [c for c in t.children if isinstance(c, Tree) or (isinstance(c, Token) and c.type in
                        ("ESCAPED_STRING", "SINGLE_QUOTED_STRING"))]
            if len(operands) != 2:
                continue
            for ref_side, lit_side in ((operands[0], operands[1]), (operands[1], operands[0])):
                ref = _prop_ref(ref_side)
                if ref is None or ref[0] not in var_labels:
                    continue
                if op == "in_op":
                    lits = [_string_token(e) for e in (lit_side.children if isinstance(lit_side, Tree)
                                                       and lit_side.data == "list_lit" else [])]
                else:
                    lits = [_string_token(lit_side)]
                for tok in lits:
                    if tok is not None:
                        sites.append((var_labels[ref[0]], ref[1], tok))

    edits: dict[int, tuple[int, str]] = {}
    for labels, prop, tok in sites:
        value = _decode(tok)
        stored = idx.resolve(labels, prop, value)
        if stored is None or stored == value:
            continue
        edits[tok.start_pos] = (tok.end_pos, _encode(stored, str(tok)[0]))
        result.changes.append(f"{prop} {value!r} -> {stored!r} (stored value for {'|'.join(sorted(labels))})")

    q = query
    for start in sorted(edits, reverse=True):
        end, text = edits[start]
        q = q[:start] + text + q[end:]
    result.query = q
    return result
