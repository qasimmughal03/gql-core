"""In-memory property graph.

Three primary stores (nodes, edges, adjacency) plus a label index.
All mutations are idempotent on ID; re-adding a node or edge merges
properties into the existing record (new keys win on conflict).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Node:
    id: Any
    label: str
    props: dict[str, Any] = field(default_factory=dict)
    labels: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.labels and self.label and self.label != "Node":
            self.labels = (self.label,)


@dataclass
class Edge:
    id: Any
    label: str
    src: Any
    dst: Any
    props: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Path:
    nodes: tuple[Node, ...]
    relationships: tuple[Edge, ...]

    def __len__(self) -> int:
        return len(self.relationships)


class PropertyGraph:
    def __init__(self) -> None:
        self._nodes: dict[Any, Node] = {}
        self._edges: dict[Any, Edge] = {}
        self._out: dict[Any, list[Any]] = {}
        self._in: dict[Any, list[Any]] = {}
        self._by_label: dict[str, set[Any]] = {}
        self._edge_by_label: dict[str, set[Any]] = {}
        self._parameters: dict[str, Any] = {}
        self._procedures: dict[str, Any] = {}
        # Marker set used by ingestion to short-circuit derived-edge
        # materialization (e.g. TEAMMATES_WITH) on re-ingest of the same match.
        self.seen_match_ids: set[str] = set()

    # ── Mutations ─────────────────────────────────────────────────

    def add_node(self, node: Node, *, strict: bool = False) -> None:
        if node.id is None or node.id == "":
            raise ValueError(f"Node identifier cannot be empty or None: {node.id!r}")
        existing = self._nodes.get(node.id)
        if existing is None:
            self._nodes[node.id] = node
            self._out.setdefault(node.id, [])
            self._in.setdefault(node.id, [])
            all_labels = getattr(node, "labels", ()) or (node.label,)
            for lbl in all_labels:
                self._by_label.setdefault(lbl, set()).add(node.id)
            return
        if strict:
            raise ValueError(f"Duplicate node identifier collision: {node.id!r} already exists")
        if existing.label != node.label:
            raise ValueError(
                f"Node {node.id!r} already exists with label {existing.label!r}, "
                f"refusing to relabel as {node.label!r}"
            )
        existing.props.update(node.props)

    def add_edge(self, edge: Edge, *, strict: bool = False) -> None:
        if edge.id is None or edge.id == "":
            raise ValueError(f"Edge identifier cannot be empty or None: {edge.id!r}")
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
        if strict:
            raise ValueError(f"Duplicate edge identifier collision: {edge.id!r} already exists")
        if (existing.label, existing.src, existing.dst) != (edge.label, edge.src, edge.dst):
            raise ValueError(
                f"Edge {edge.id!r} already exists with different label/endpoints"
            )
        existing.props.update(edge.props)

    def delete_edge(self, edge_id: Any) -> bool:
        """Delete an edge from the graph. Returns True if deleted, False if not found."""
        edge = self._edges.pop(edge_id, None)
        if edge is None:
            return False
        if edge.src in self._out:
            try:
                self._out[edge.src].remove(edge_id)
            except ValueError:
                pass
        if edge.dst in self._in:
            try:
                self._in[edge.dst].remove(edge_id)
            except ValueError:
                pass
        if edge.label in self._edge_by_label:
            self._edge_by_label[edge.label].discard(edge_id)
        return True

    def delete_node(self, node_id: Any, *, detach: bool = False) -> bool:
        """Delete a node from the graph.
        
        If detach is False and the node has incident edges, raises RuntimeError.
        If detach is True, deletes all incident edges first.
        Returns True if deleted, False if not found.
        """
        node = self._nodes.get(node_id)
        if node is None:
            return False
        out_edges = list(self._out.get(node_id, ()))
        in_edges = list(self._in.get(node_id, ()))
        if (out_edges or in_edges) and not detach:
            raise RuntimeError(
                f"Cannot delete node {node_id!r} because it still has relationships. "
                "To delete this node, you must first delete its relationships or use DETACH DELETE."
            )
        for eid in out_edges + in_edges:
            self.delete_edge(eid)
        self._nodes.pop(node_id, None)
        self._out.pop(node_id, None)
        self._in.pop(node_id, None)
        all_labels = getattr(node, "labels", ()) or (node.label,)
        for lbl in all_labels:
            if lbl in self._by_label:
                self._by_label[lbl].discard(node_id)
        return True

    # ── Reads ─────────────────────────────────────────────────────

    def get_node(self, node_id: Any) -> Node | None:
        return self._nodes.get(node_id)

    def has_node(self, node_id: Any) -> bool:
        return node_id in self._nodes

    def get_edge(self, edge_id: Any) -> Edge | None:
        return self._edges.get(edge_id)

    def has_edge(self, edge_id: Any) -> bool:
        return edge_id in self._edges

    def outgoing(self, node_id: Any, label: str | None = None) -> list[Edge]:
        edges = []
        labels = set(label.split("|")) if label and "|" in label else ({label} if label is not None else None)
        for eid in self._out.get(node_id, ()):
            e = self._edges[eid]
            if labels is None or e.label in labels:
                edges.append(e)
        return edges

    def incoming(self, node_id: Any, label: str | None = None) -> list[Edge]:
        edges = []
        labels = set(label.split("|")) if label and "|" in label else ({label} if label is not None else None)
        for eid in self._in.get(node_id, ()):
            e = self._edges[eid]
            if labels is None or e.label in labels:
                edges.append(e)
        return edges

    def neighbors(
        self,
        node_id: Any,
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
        labels = set(label.split("|")) if label and "|" in label else ({label} if label is not None else None)
        if direction in {"out", "both"}:
            for eid in self._out.get(node_id, ()):
                edge = self._edges[eid]
                if labels is not None and edge.label not in labels:
                    continue
                yield edge, self._nodes[edge.dst]
        if direction in {"in", "both"}:
            for eid in self._in.get(node_id, ()):
                edge = self._edges[eid]
                if labels is not None and edge.label not in labels:
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

    def __bool__(self) -> bool:
        return True

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
        """Construct a PropertyGraph from any NetworkX graph or graph-like object.

        Imports node and edge attributes as properties.
        Preserves node IDs in their native type (int, str, etc.) without string coercion.
        Supports MultiGraph parallel edges.
        Rejects empty/None node identifiers and duplicate identifier collisions.
        """
        graph = cls()
        for node_id, data in G.nodes(data=True):
            if node_id is None or node_id == "":
                raise ValueError(f"NetworkX node identifier cannot be empty or None: {node_id!r}")
            if node_id in graph._nodes:
                raise ValueError(f"Duplicate node identifier collision in NetworkX graph: {node_id!r}")
            props = dict(data)
            label = None
            for key in ("label", "@type"):
                if key in props and props[key] is not None and props[key] != "":
                    label = str(props.pop(key))
                    break
            if not label:
                label = default_node_label
            graph.add_node(Node(id=node_id, label=label, props=props))

        is_multi = hasattr(G, "is_multigraph") and G.is_multigraph()
        edges_iter = G.edges(keys=True, data=True) if is_multi else G.edges(data=True)

        for idx, edge_tuple in enumerate(edges_iter):
            if is_multi:
                src, dst, key, data = edge_tuple
            else:
                src, dst, data = edge_tuple
                key = idx

            if src is None or src == "" or dst is None or dst == "":
                raise ValueError(f"NetworkX edge endpoints cannot be empty or None: src={src!r}, dst={dst!r}")
            if src not in graph._nodes:
                graph.add_node(Node(id=src, label=default_node_label))
            if dst not in graph._nodes:
                graph.add_node(Node(id=dst, label=default_node_label))

            props = dict(data)
            label = None
            for lk in ("label", "@type"):
                if lk in props and props[lk] is not None and props[lk] != "":
                    label = str(props.pop(lk))
                    break
            if not label:
                label = default_edge_label

            eid = None
            for ik in ("id", "@id"):
                if ik in props and props[ik] is not None and props[ik] != "":
                    eid = props.pop(ik)
                    break
            if eid is None or eid == "":
                eid = f"{label}:{src}:{dst}:{key if is_multi else idx}"

            if eid in graph._edges:
                raise ValueError(f"Duplicate edge identifier collision: {eid!r}")

            graph.add_edge(Edge(id=eid, label=label, src=src, dst=dst, props=props))

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
        """Construct a PropertyGraph from an iterable of edge tuples.

        Supported tuple formats:
            (src, dst)
            (src, dst, label)
            (src, dst, label, props_dict)
            (src, dst, label, props_dict, edge_id)
        """
        graph = cls()
        for idx, item in enumerate(edges):
            if len(item) == 2:
                src, dst = item
                label = default_edge_label
                props = {}
                eid = None
            elif len(item) == 3:
                src, dst, label = item
                props = {}
                eid = None
            elif len(item) == 4:
                src, dst, label, props = item
                props = dict(props)
                eid = None
            elif len(item) >= 5:
                src, dst, label, props, eid = item[:5]
                props = dict(props)
            else:
                continue

            if src is None or src == "" or dst is None or dst == "":
                raise ValueError(f"Edge endpoints cannot be empty or None: src={src!r}, dst={dst!r}")

            if src not in graph._nodes:
                graph.add_node(Node(id=src, label=default_node_label))
            if dst not in graph._nodes:
                graph.add_node(Node(id=dst, label=default_node_label))

            if eid is None or eid == "":
                eid = f"{label}:{src}:{dst}:{idx}"

            if eid in graph._edges:
                raise ValueError(f"Duplicate edge identifier collision: {eid!r}")

            graph.add_edge(Edge(id=eid, label=str(label), src=src, dst=dst, props=props))
            if not directed:
                rev_eid = f"{eid}_rev"
                if rev_eid in graph._edges:
                    raise ValueError(f"Duplicate edge identifier collision: {rev_eid!r}")
                graph.add_edge(Edge(id=rev_eid, label=str(label), src=dst, dst=src, props=props))
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
            nid = None
            for key in ("id", "@id"):
                if key in item and item[key] is not None and item[key] != "":
                    nid = item.pop(key)
                    break
            if nid is None or nid == "":
                raise ValueError(f"Record missing identifier or identifier is empty: {raw!r}")
            if nid in graph._nodes:
                raise ValueError(f"Duplicate node identifier collision: {nid!r} already exists")

            label = None
            for key in ("label", "@type"):
                if key in item and item[key] is not None and item[key] != "":
                    label = str(item.pop(key))
                    break
            if not label:
                label = "Node"

            graph.add_node(Node(id=nid, label=label, props=item))

        for idx, raw in enumerate(edges):
            item = dict(raw)
            src = None
            for key in ("src", "@src", "source", "from"):
                if key in item and item[key] is not None and item[key] != "":
                    src = item.pop(key)
                    break
            if src is None or src == "":
                raise ValueError(f"Edge record missing source identifier or source is empty: {raw!r}")

            dst = None
            for key in ("dst", "@dst", "target", "to"):
                if key in item and item[key] is not None and item[key] != "":
                    dst = item.pop(key)
                    break
            if dst is None or dst == "":
                raise ValueError(f"Edge record missing destination identifier or destination is empty: {raw!r}")

            label = None
            for key in ("label", "@type", "type"):
                if key in item and item[key] is not None and item[key] != "":
                    label = str(item.pop(key))
                    break
            if not label:
                label = "CONNECTED_TO"

            eid = None
            for key in ("id", "@id"):
                if key in item and item[key] is not None and item[key] != "":
                    eid = item.pop(key)
                    break
            if eid is None or eid == "":
                eid = f"{label}:{src}:{dst}:{idx}"

            if src not in graph._nodes:
                graph.add_node(Node(id=src, label="Node"))
            if dst not in graph._nodes:
                graph.add_node(Node(id=dst, label="Node"))

            if eid in graph._edges:
                raise ValueError(f"Duplicate edge identifier collision: {eid!r}")

            graph.add_edge(Edge(id=eid, label=label, src=src, dst=dst, props=item))
        return graph

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PropertyGraph:
        """Construct a PropertyGraph from a dictionary with 'nodes' and 'edges' lists."""
        return cls.from_records(data.get("nodes", ()), data.get("edges", ()))

