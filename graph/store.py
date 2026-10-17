"""In-memory property graph.

Three primary stores (nodes, edges, adjacency) plus a label index.
All mutations are idempotent on ID; re-adding a node or edge merges
properties into the existing record (new keys win on conflict).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Node:
    id: str
    label: str
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    id: str
    label: str
    src: str
    dst: str
    props: dict[str, Any] = field(default_factory=dict)


class PropertyGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}
        self._out: dict[str, list[str]] = {}
        self._in: dict[str, list[str]] = {}
        self._by_label: dict[str, set[str]] = {}
        self._edge_by_label: dict[str, set[str]] = {}
        # Marker set used by ingestion to short-circuit derived-edge
        # materialization (e.g. TEAMMATES_WITH) on re-ingest of the same match.
        self.seen_match_ids: set[str] = set()

    # ── Mutations ─────────────────────────────────────────────────

    def add_node(self, node: Node) -> None:
        existing = self._nodes.get(node.id)
        if existing is None:
            self._nodes[node.id] = node
            self._out.setdefault(node.id, [])
            self._in.setdefault(node.id, [])
            self._by_label.setdefault(node.label, set()).add(node.id)
            return
        if existing.label != node.label:
            raise ValueError(
                f"Node {node.id!r} already exists with label {existing.label!r}, "
                f"refusing to relabel as {node.label!r}"
            )
        existing.props.update(node.props)

    def add_edge(self, edge: Edge) -> None:
        if edge.src not in self._nodes:
            raise KeyError(f"Edge {edge.id!r} src node {edge.src!r} not in graph")
        if edge.dst not in self._nodes:
            raise KeyError(f"Edge {edge.id!r} dst node {edge.dst!r} not in graph")
        existing = self._edges.get(edge.id)
        if existing is None:
            self._edges[edge.id] = edge
            self._out.setdefault(edge.src, []).append(edge.id)
            self._in.setdefault(edge.dst, []).append(edge.id)
            self._edge_by_label.setdefault(edge.label, set()).add(edge.id)
            return
        if (existing.label, existing.src, existing.dst) != (edge.label, edge.src, edge.dst):
            raise ValueError(
                f"Edge {edge.id!r} already exists with different label/endpoints"
            )
        existing.props.update(edge.props)

    # ── Reads ─────────────────────────────────────────────────────

    def get_node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def get_edge(self, edge_id: str) -> Edge | None:
        return self._edges.get(edge_id)

    def neighbors(
        self,
        node_id: str,
        *,
        label: str | None = None,
        direction: str = "out",
    ) -> Iterator[tuple[Edge, Node]]:
        """Yield (edge, neighbor_node) pairs.

        direction: 'out' | 'in' | 'both'.
        label: edge-label filter (None = all labels).
        """
        if direction not in {"out", "in", "both"}:
            raise ValueError(f"direction must be 'out'|'in'|'both', got {direction!r}")
        if direction in {"out", "both"}:
            for eid in self._out.get(node_id, ()):
                edge = self._edges[eid]
                if label is not None and edge.label != label:
                    continue
                yield edge, self._nodes[edge.dst]
        if direction in {"in", "both"}:
            for eid in self._in.get(node_id, ()):
                edge = self._edges[eid]
                if label is not None and edge.label != label:
                    continue
                yield edge, self._nodes[edge.src]

    def nodes_by_label(self, label: str) -> Iterator[Node]:
        for nid in self._by_label.get(label, ()):
            yield self._nodes[nid]

    def edges_by_label(self, label: str) -> Iterator[Edge]:
        for eid in self._edge_by_label.get(label, ()):
            yield self._edges[eid]

    # ── Inspection ────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._nodes)

    def stats(self) -> dict[str, Any]:
        return {
            "nodes": len(self._nodes),
            "edges": len(self._edges),
            "by_label": {label: len(ids) for label, ids in self._by_label.items()},
            "edges_by_label": {
                label: len(ids) for label, ids in self._edge_by_label.items()
            },
        }

    # ── Zero-Friction Ingestion Adapters ──────────────────────────

    @classmethod
    def from_networkx(
        cls,
        G: Any,
        *,
        default_node_label: str = "Node",
        default_edge_label: str = "CONNECTED_TO",
    ) -> PropertyGraph:
        """Construct a PropertyGraph from any NetworkX graph or graph-like object."""
        graph = cls()
        for node_id, data in G.nodes(data=True):
            props = dict(data)
            label = str(props.pop("label", None) or props.pop("@type", None) or default_node_label)
            graph.add_node(Node(id=str(node_id), label=label, props=props))

        for idx, (src, dst, *rest) in enumerate(G.edges(data=True)):
            data = rest[0] if rest else {}
            props = dict(data)
            label = str(props.pop("label", None) or props.pop("@type", None) or default_edge_label)
            edge_id = str(props.pop("id", None) or props.pop("@id", None) or f"{label}:{src}:{dst}:{idx}")
            graph.add_edge(Edge(id=edge_id, label=label, src=str(src), dst=str(dst), props=props))
        return graph

    @classmethod
    def from_edges(
        cls,
        edges: Iterable[tuple],
        *,
        directed: bool = True,
        default_node_label: str = "Node",
        default_edge_label: str = "CONNECTED_TO",
    ) -> PropertyGraph:
        """Construct a PropertyGraph from an iterable of edge tuples."""
        graph = cls()
        for idx, item in enumerate(edges):
            if len(item) == 2:
                src, dst = item
                label = default_edge_label
                props = {}
            elif len(item) == 3:
                src, dst, label = item
                props = {}
            elif len(item) >= 4:
                src, dst, label, props = item[:4]
                props = dict(props)
            else:
                continue

            src_str, dst_str = str(src), str(dst)
            if src_str not in graph._nodes:
                graph.add_node(Node(id=src_str, label=default_node_label))
            if dst_str not in graph._nodes:
                graph.add_node(Node(id=dst_str, label=default_node_label))

            eid = f"{label}:{src_str}:{dst_str}:{idx}"
            graph.add_edge(Edge(id=eid, label=str(label), src=src_str, dst=dst_str, props=props))
            if not directed:
                rev_eid = f"{label}:{dst_str}:{src_str}:{idx}_rev"
                graph.add_edge(Edge(id=rev_eid, label=str(label), src=dst_str, dst=src_str, props=props))
        return graph

    @classmethod
    def from_records(
        cls,
        nodes: Iterable[dict[str, Any]],
        edges: Iterable[dict[str, Any]] = (),
    ) -> PropertyGraph:
        """Construct a PropertyGraph from lists/iterables of node and edge dictionaries."""
        graph = cls()
        for raw in nodes:
            item = dict(raw)
            nid = str(item.pop("id", None) or item.pop("@id", None) or item.pop("name", None))
            label = str(item.pop("label", None) or item.pop("@type", None) or "Node")
            graph.add_node(Node(id=nid, label=label, props=item))

        for idx, raw in enumerate(edges):
            item = dict(raw)
            src = str(item.pop("src", None) or item.pop("@src", None) or item.pop("source", None) or item.pop("from", None))
            dst = str(item.pop("dst", None) or item.pop("@dst", None) or item.pop("target", None) or item.pop("to", None))
            label = str(item.pop("label", None) or item.pop("@type", None) or "CONNECTED_TO")
            eid = str(item.pop("id", None) or item.pop("@id", None) or f"{label}:{src}:{dst}:{idx}")
            if src not in graph._nodes:
                graph.add_node(Node(id=src, label="Node"))
            if dst not in graph._nodes:
                graph.add_node(Node(id=dst, label="Node"))
            graph.add_edge(Edge(id=eid, label=label, src=src, dst=dst, props=item))
        return graph

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PropertyGraph:
        """Construct a PropertyGraph from a dictionary with 'nodes' and 'edges' lists."""
        return cls.from_records(data.get("nodes", ()), data.get("edges", ()))

