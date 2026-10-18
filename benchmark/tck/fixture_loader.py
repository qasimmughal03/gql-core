"""openCypher TCK Fixture Loader.

Parses Cypher CREATE fixture statements into an in-memory PropertyGraph using
GQL-Core's public graph mutation API (PropertyGraph, Node, Edge).

Note: This fixture loader exists solely to construct test graphs for compatibility
testing and does NOT establish support for query-language mutations in GQL-Core.
"""

from __future__ import annotations

import re
from typing import Any
from gql_core.graph import Edge, Node, PropertyGraph


def _parse_props(props_str: str | None) -> dict[str, Any]:
    """Parse Cypher property map literal like {id: 0, name: 'Alice', active: true}."""
    if not props_str or not props_str.strip():
        return {}
    props: dict[str, Any] = {}
    pattern = re.compile(
        r"([a-zA-Z0-9_]+)\s*:\s*('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|\[[^\]]*\]|true|false|null|-?[0-9]+(?:\.[0-9]+)?)"
    )
    for m in pattern.finditer(props_str):
        k = m.group(1)
        raw_v = m.group(2).strip()
        if raw_v == "true":
            v: Any = True
        elif raw_v == "false":
            v = False
        elif raw_v == "null":
            v = None
        elif (raw_v.startswith("'") and raw_v.endswith("'")) or (raw_v.startswith('"') and raw_v.endswith('"')):
            v = raw_v[1:-1].replace("\\'", "'").replace('\\"', '"')
        elif raw_v.startswith("[") and raw_v.endswith("]"):
            items = [x.strip().strip("'\"") for x in raw_v[1:-1].split(",") if x.strip()]
            v = items
        elif "." in raw_v:
            try:
                v = float(raw_v)
            except ValueError:
                v = raw_v
        else:
            try:
                v = int(raw_v)
            except ValueError:
                v = raw_v
        props[k] = v
    return props


def load_cypher_create_fixture(create_clause: str, graph: PropertyGraph | None = None) -> PropertyGraph:
    """Parse one or more CREATE patterns and populate a PropertyGraph."""
    if graph is None:
        graph = PropertyGraph()

    text = create_clause.strip().rstrip(";").strip()
    if not text:
        return graph

    try:
        from gql_core import run as run_query
        run_query(text, graph)
        return graph
    except Exception:
        pass

    # Handle UNWIND range(lo, hi) AS var CREATE (...)
    m_unwind = re.match(
        r"^UNWIND\s+range\s*\(\s*([0-9]+)\s*,\s*([0-9]+)\s*\)\s*AS\s+[a-zA-Z0-9_]+\s*CREATE\s+(.*)$",
        text,
        re.I | re.DOTALL,
    )
    if m_unwind:
        lo = int(m_unwind.group(1))
        hi = int(m_unwind.group(2))
        inner_create = m_unwind.group(3).strip()
        for _ in range(lo, hi + 1):
            load_cypher_create_fixture("CREATE " + inner_create, graph)
        return graph

    # Split multiple CREATE statements if present
    if ";" in text or len(re.findall(r"\bCREATE\b", text, flags=re.I)) > 1:
        clauses = [c.strip() for c in re.split(r";|\bCREATE\b", text, flags=re.I) if c.strip()]
        for cl in clauses:
            load_cypher_create_fixture("CREATE " + cl, graph)
        return graph

    if text.upper().startswith("CREATE"):
        text = text[6:].strip()

    # Split top-level comma-separated pattern elements
    elements: list[str] = []
    depth = 0
    curr: list[str] = []
    for char in text:
        if char in "({[":
            depth += 1
        elif char in ")}]":
            depth -= 1
        if char == "," and depth == 0:
            elem = "".join(curr).strip()
            if elem:
                elements.append(elem)
            curr = []
        else:
            curr.append(char)
    if curr:
        elem = "".join(curr).strip()
        if elem:
            elements.append(elem)

    node_regex = re.compile(
        r"^\((?P<var>[a-zA-Z0-9_]*)(?::(?P<labels>[a-zA-Z0-9_:]+))?(?:\s*\{(?P<props>[^}]+)\})?\)$"
    )
    rel_regex = re.compile(
        r"^(?P<in><-|-)?(?:\[(?P<var>[a-zA-Z0-9_]*)(?::(?P<label>[a-zA-Z0-9_]+))?(?:\s*\{(?P<props>[^}]+)\})?\]|(?P<anon_out>-->)|(?P<anon_in><--)|(?P<anon_undir>--))(?P<out>->|-)?$"
    )
    rel_pat = r"<-\[[^\]]*\]->?|<-\[[^\]]*\]-?|-\[[^\]]*\]->?|-\[[^\]]*\]-?|-->|<--|--"
    tok_regex = re.compile(rf"(\([^)]*\)|{rel_pat})")

    var_to_id: dict[str, str] = {nid: nid for nid in graph._nodes}
    auto_id = len(graph._nodes) + len(graph._edges)

    for elem in elements:
        tokens = [m.group(1).strip() for m in tok_regex.finditer(elem)]
        prev_node_id: str | None = None
        pending_rel: tuple[str | None, str, dict[str, Any], str] | None = None

        for tok in tokens:
            m_node = node_regex.match(tok)
            if m_node:
                n_var = m_node.group("var") or None
                labels_str = m_node.group("labels") or "Node"
                primary_label = labels_str.split(":")[0] if labels_str else "Node"
                props = _parse_props(m_node.group("props"))

                if n_var and (n_var in var_to_id or n_var in graph._nodes):
                    n_id = var_to_id.get(n_var, n_var)
                    existing = graph._nodes.get(n_id)
                    if existing:
                        existing.props.update(props)
                else:
                    auto_id += 1
                    if n_var:
                        n_id = str(n_var)
                        var_to_id[n_var] = n_id
                    else:
                        n_id = f"node_{auto_id}"

                    all_labels = tuple(lbl for lbl in labels_str.split(":") if lbl) if labels_str else ()
                    node = Node(id=n_id, label=primary_label, props=props, labels=all_labels)
                    graph.add_node(node)

                if pending_rel and prev_node_id:
                    r_var, r_label, r_props, r_dir = pending_rel
                    auto_id += 1
                    r_id = r_var or f"rel_{auto_id}"
                    if r_dir == "out":
                        src, dst = prev_node_id, n_id
                    elif r_dir == "in":
                        src, dst = n_id, prev_node_id
                    else:
                        src, dst = prev_node_id, n_id
                    edge = Edge(id=r_id, label=r_label, src=src, dst=dst, props=r_props)
                    graph.add_edge(edge)
                    if r_dir == "undirected":
                        edge_rev = Edge(id=f"{r_id}_rev", label=r_label, src=dst, dst=src, props=r_props)
                        graph.add_edge(edge_rev)
                    pending_rel = None

                prev_node_id = n_id
            else:
                m_rel = rel_regex.match(tok)
                if m_rel:
                    r_var = m_rel.group("var") or None
                    r_label = m_rel.group("label") or "CONNECTED_TO"
                    r_props = _parse_props(m_rel.group("props"))
                    is_left = bool((m_rel.group("in") and "<" in m_rel.group("in")) or m_rel.group("anon_in"))
                    is_right = bool((m_rel.group("out") and ">" in m_rel.group("out")) or m_rel.group("anon_out"))
                    if is_left and not is_right:
                        r_dir = "in"
                    elif is_right and not is_left:
                        r_dir = "out"
                    else:
                        r_dir = "undirected"
                    pending_rel = (r_var, r_label, r_props, r_dir)

    return graph
