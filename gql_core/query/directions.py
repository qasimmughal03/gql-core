"""Schema-based correction of relationship directions in generated Cypher.

LLMs that write Cypher often reverse a relationship: the schema says
``(:Movie)-[:written_by]->(:Person)`` and the model writes
``(p:Person)-[:written_by]->(m:Movie)``. Such a query is valid Cypher, runs, and
returns nothing. :func:`correct_relationship_directions` reverses an arrow only
when the schema makes the written direction impossible and the opposite
direction possible for the labels involved. It changes nothing else in the query
text, never touches undirected relationships, and leaves a relationship alone
when its type or end labels are unknown or both directions are allowed.

The same idea is used by LangChain's ``CypherQueryCorrector``
(``GraphCypherQAChain(validate_cypher=True)``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from lark import Lark, Token, Tree

from gql_core.query.parser import _GRAMMAR

Triple = tuple[str, str, str]  # (relationship type, source label, target label)

_DIRECTED = {"rel_out": "out", "rel_in": "in"}
_PARSERS: dict[str, Lark] = {}


def _parser(kind: str) -> Lark:
    if kind not in _PARSERS:
        _PARSERS[kind] = Lark.open(str(_GRAMMAR), parser=kind, maybe_placeholders=False,
                                   keep_all_tokens=True, propagate_positions=True)
    return _PARSERS[kind]


def _parse_tree(query: str) -> Tree:
    try:
        return _parser("lalr").parse(query)
    except Exception:  # noqa: BLE001 - same fallback as gql_core.query.parser.parse
        return _parser("earley").parse(query)


@dataclass
class DirectionCorrection:
    """Result of :func:`correct_relationship_directions`."""

    query: str
    original: str
    changes: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.changes)


def schema_triples(schema: Any) -> set[Triple]:
    """Normalise a schema to ``{(rel_type, source_label, target_label)}``.

    Accepts a :class:`~gql_core.graph.PropertyGraph` (every edge is scanned, and every
    label of each endpoint counts), a dict with a ``relations`` list of
    ``{"label", "subj_label", "obj_label"}`` entries (the CypherBench schema format),
    or an iterable of triples.
    """
    from gql_core.graph import PropertyGraph

    if isinstance(schema, PropertyGraph):
        out: set[Triple] = set()
        nodes = schema._nodes
        for e in schema._edges.values():
            s, d = nodes.get(e.src), nodes.get(e.dst)
            if s is None or d is None:
                continue
            for sl in (s.labels or (s.label,)):
                for dl in (d.labels or (d.label,)):
                    out.add((e.label, sl, dl))
        return out
    if isinstance(schema, dict):
        return {(r["label"], r["subj_label"], r["obj_label"]) for r in schema.get("relations", ())}
    return {tuple(t) for t in schema}  # type: ignore[misc]


def _text(t: Any) -> str:
    if isinstance(t, Token):
        s = str(t)
        return s[1:-1] if s.startswith("`") and s.endswith("`") else s
    return "".join(_text(c) for c in t.children)


def _node_info(node_pat: Tree) -> tuple[str | None, set[str]]:
    var = None
    labels: set[str] = set()
    for c in node_pat.children:
        if isinstance(c, Tree) and c.data == "ident":
            var = _text(c)
        elif isinstance(c, Tree) and c.data == "label_name":
            labels.add(_text(c))
    return var, labels


def _rel_types(rel: Tree) -> list[str]:
    for c in rel.children:
        if isinstance(c, Tree) and c.data == "edge_label":
            return [_text(x) for x in c.children if isinstance(x, Tree) and x.data == "label_name"]
    return []


def _chains(tree: Tree) -> Iterable[list[Tree]]:
    """Yield each node/relationship sequence: [node, rel, node, rel, node, ...]."""
    for sub in tree.iter_subtrees():
        kids = [c for c in sub.children if isinstance(c, Tree) and (c.data == "node_pat" or c.data.startswith("rel_"))]
        if any(k.data.startswith("rel_") for k in kids):
            yield kids


def correct_relationship_directions(query: str, schema: Any) -> DirectionCorrection:
    """Reverse relationship arrows that the schema makes impossible.

    ``schema`` is anything :func:`schema_triples` accepts; pass precomputed triples
    to avoid rescanning a large graph. Queries that do not parse are returned
    unchanged.
    """
    triples = schema if isinstance(schema, set) else schema_triples(schema)
    result = DirectionCorrection(query=query, original=query)
    try:
        tree = _parse_tree(query)
    except Exception:  # noqa: BLE001
        return result

    by_type: dict[str, set[tuple[str, str]]] = {}
    for t, s, d in triples:
        by_type.setdefault(t, set()).add((s, d))

    var_labels: dict[str, set[str]] = {}
    for np in tree.find_data("node_pat"):
        var, labels = _node_info(np)
        if var and labels:
            var_labels.setdefault(var, set()).update(labels)

    def labels_of(np: Tree) -> set[str]:
        var, labels = _node_info(np)
        return labels or var_labels.get(var or "", set())

    def allowed(rel_type: str, src: set[str], dst: set[str]) -> bool:
        return any((not src or s in src) and (not dst or d in dst) for s, d in by_type[rel_type])

    edits: list[tuple[int, int, str]] = []
    for chain in _chains(tree):
        for i in range(1, len(chain) - 1, 2):
            rel, left, right = chain[i], chain[i - 1], chain[i + 1]
            direction = _DIRECTED.get(rel.data)
            types = _rel_types(rel)
            if direction is None or not types or any(t not in by_type for t in types):
                continue
            src, dst = (labels_of(left), labels_of(right)) if direction == "out" else (labels_of(right), labels_of(left))
            if not src and not dst:
                continue
            if any(allowed(t, src, dst) for t in types) or not all(allowed(t, dst, src) for t in types):
                continue
            toks = [c for c in rel.children if isinstance(c, Token)]
            head, tail = toks[0], toks[-1]
            if direction == "out":   # -[ ... ]->   becomes   <-[ ... ]-
                edits += [(head.start_pos, head.end_pos, "<-["), (tail.start_pos, tail.end_pos, "]-")]
            else:                    # <-[ ... ]-   becomes   -[ ... ]->
                edits += [(head.start_pos, head.end_pos, "-["), (tail.start_pos, tail.end_pos, "]->")]
            pretty = "|".join(types)
            s_txt = ":" + "|".join(sorted(src)) if src else ""
            d_txt = ":" + "|".join(sorted(dst)) if dst else ""
            result.changes.append(f"reversed ({s_txt})-[:{pretty}]->({d_txt}); the schema only has it the other way")

    q = query
    for start, end, text in sorted(set(edits), reverse=True):
        q = q[:start] + text + q[end:]
    result.query = q
    return result
