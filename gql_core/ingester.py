"""Generic graph-json ingestion.

Reads graph data from JSON files in the gql-graph-json format and
populates a PropertyGraph with SHACL validation.

Format (gql-graph-json)::

    {
      "nodes": [
        {"@id": "p1", "@type": "Person", "name": "Alice", "age": 30}
      ],
      "edges": [
        {"@id": "e1", "@type": "KNOWS", "@src": "p1", "@dst": "p2", "since": 2020}
      ]
    }

- @id on nodes is required and must be unique.
- @type on nodes/edges is required and must match a label in shapes.yaml.
- @src / @dst on edges must reference existing node @ids.
- @id on edges is optional — auto-generated as "{label}:{src}:{dst}".
- All other keys become properties on the node or edge.
- Reserved keys: @id, @type, @src, @dst, @nodes, @edges.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gql_core.graph import Edge, Node, PropertyGraph
from gql_core.validator import ShapeValidator, ShapeViolationError

# Keys reserved by the format — everything else is a property.
_RESERVED = {"@id", "@type", "@src", "@dst", "@nodes", "@edges"}


def _edge_id(label: str, src: str, dst: str) -> str:
    """Deterministic edge ID when none is provided."""
    return f"{label}:{src}:{dst}"


def _extract_props(raw: dict[str, Any]) -> dict[str, Any]:
    """Return every key that isn't a reserved @-key."""
    return {k: v for k, v in raw.items() if k not in _RESERVED}


@dataclass
class IngestReport:
    """Summary produced after ingesting a file or directory."""

    files: int = 0
    nodes: int = 0
    edges: int = 0
    skipped: int = 0
    errors: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "files": self.files,
            "nodes": self.nodes,
            "edges": self.edges,
            "skipped": self.skipped,
            "errors": list(self.errors),
        }


class GraphIngester:
    """Ingest gql-graph-json files into a PropertyGraph.

    Every node and edge is validated through the ShapeValidator before
    insertion.  ID collisions are handled idempotently by the graph store
    (properties merge, labels must agree).

    Parameters
    ----------
    graph : PropertyGraph
        Target graph (mutated in-place).
    validator : ShapeValidator
        Schema validator loaded from the user's shapes.yaml.
    """

    def __init__(self, graph: PropertyGraph, validator: ShapeValidator) -> None:
        self.graph = graph
        self.validator = validator

    # ── Public API ──────────────────────────────────────────────────

    def ingest_data(self, data: dict) -> tuple[int, int]:
        """Ingest raw graph data from a parsed JSON dict.

        Returns (nodes_added, edges_added).
        """
        nodes_before = len(self.graph)
        edges_before = len(self.graph._edges)

        # Two-pass: nodes first (edges need endpoints to exist).
        for raw in data.get("nodes") or ():
            self._ingest_node(raw)
        for raw in data.get("edges") or ():
            self._ingest_edge(raw)

        return (
            len(self.graph) - nodes_before,
            len(self.graph._edges) - edges_before,
        )

    def ingest_file(self, path: str | Path) -> tuple[int, int]:
        """Ingest a single gql-graph-json file.

        Returns (nodes_added, edges_added).
        """
        resolved = Path(path)
        with resolved.open() as f:
            data = json.load(f)
        return self.ingest_data(data)

    def ingest_directory(self, dirpath: str | Path) -> IngestReport:
        """Ingest all *.json files in a directory (sorted by name).

        Returns an IngestReport summarising what was loaded.
        """
        report = IngestReport()
        dir_path = Path(dirpath)
        if not dir_path.is_dir():
            raise NotADirectoryError(str(dir_path))

        for path in sorted(dir_path.glob("*.json")):
            try:
                n, e = self.ingest_file(path)
                report.files += 1
                report.nodes += n
                report.edges += e
            except (json.JSONDecodeError, ShapeViolationError, KeyError) as exc:
                report.errors.append(
                    {
                        "file": str(path),
                        "reason": type(exc).__name__,
                        "message": str(exc),
                    }
                )
        return report

    # ── Internals ───────────────────────────────────────────────────

    def _ingest_node(self, raw: dict) -> None:
        nid = raw.get("@id")
        label = raw.get("@type")
        if not nid:
            raise KeyError(f"Node missing @id: {raw}")
        if not label:
            raise KeyError(f"Node {nid!r} missing @type")

        props = _extract_props(raw)
        props["id"] = nid
        self.validator.validate_node(label, props)
        self.graph.add_node(Node(id=nid, label=label, props=props))

    def _ingest_edge(self, raw: dict) -> None:
        label = raw.get("@type")
        src = raw.get("@src")
        dst = raw.get("@dst")
        if not label:
            raise KeyError(f"Edge missing @type: {raw}")
        if not src:
            raise KeyError(f"Edge {label!r} missing @src")
        if not dst:
            raise KeyError(f"Edge {label!r} missing @dst")

        eid = raw.get("@id") or _edge_id(label, src, dst)
        props = _extract_props(raw)

        # Resolve endpoint labels for validation.
        src_node = self.graph.get_node(src)
        dst_node = self.graph.get_node(dst)
        if src_node is None:
            raise KeyError(f"Edge {eid!r} src node {src!r} not found in graph")
        if dst_node is None:
            raise KeyError(f"Edge {eid!r} dst node {dst!r} not found in graph")

        self.validator.validate_edge(
            label, src_node.label, dst_node.label, props
        )
        self.graph.add_edge(
            Edge(id=eid, label=label, src=src, dst=dst, props=props)
        )
