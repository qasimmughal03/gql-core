"""Generic SQLite mirror builder.

Auto-generates a normalized SQLite database from any PropertyGraph +
shapes.yaml pair. Table schemas, column types, and indexes are derived
entirely from the shape definitions — no domain knowledge required.

Usage::

    from gql_core.mirror import build_mirror
    conn = build_mirror(graph, "my-shapes.yaml", "out.db")
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from gql_core.graph import PropertyGraph
from gql_core.schema import load_shapes

# Shapes type → SQLite column affinity.
_TYPE_TO_SQL: dict[str, str] = {
    "str": "TEXT",
    "int": "INTEGER",
    "float": "REAL",
    "bool": "INTEGER",  # SQLite stores booleans as 0/1
    "list": "TEXT",     # JSON-encoded
    "dict": "TEXT",     # JSON-encoded
}


def _snake(name: str) -> str:
    """PascalCase → snake_case table name."""
    out: list[str] = []
    for ch in name:
        if ch.isupper() and out:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _column_type(col: str, type_name: str | None) -> str:
    """Map a shapes.yaml type name to an SQLite column affinity."""
    if col == "id":
        return "TEXT PRIMARY KEY"
    if type_name is None:
        return "TEXT"
    return _TYPE_TO_SQL.get(type_name, "TEXT")


def _table_plan(shapes: dict) -> dict:
    """Derive node/edge table schemas from shapes.yaml.

    Returns a dict with keys:
      node_tables: {Label: {"table": str, "columns": [(name, sql_type), ...]}}
      edge_tables: {Label: {"table": str, "src_col": str, "dst_col": str,
                             "columns": [(name, sql_type), ...],
                             "filter_indexes": [[col, ...], ...]}}
    """
    raw_nodes = shapes.get("nodes") or {}
    raw_edges = shapes.get("edges") or {}

    node_tables: dict[str, dict] = {}
    for label, shape in raw_nodes.items():
        table = shape.get("table", _snake(label))
        shape_types = shape.get("types") or {}
        # Collect all declared properties (required + optional).
        all_props: list[str] = []
        all_props.extend(shape.get("required") or ())
        all_props.extend(shape.get("optional") or ())
        seen: set[str] = set()
        columns: list[tuple[str, str]] = []
        for prop in all_props:
            if prop in seen:
                continue
            seen.add(prop)
            columns.append((prop, _column_type(prop, shape_types.get(prop))))
        # Ensure `id` is first.
        if "id" not in seen:
            columns.insert(0, ("id", "TEXT PRIMARY KEY"))
        node_tables[label] = {
            "table": table,
            "columns": columns,
        }

    edge_tables: dict[str, dict] = {}
    for label, shape in raw_edges.items():
        table = shape.get("table", _snake(label.lower()))
        src_col = shape.get("src_col", "src_id")
        dst_col = shape.get("dst_col", "dst_id")
        edge_props = shape.get("properties") or {}
        columns: list[tuple[str, str]] = [
            (src_col, "TEXT"),
            (dst_col, "TEXT"),
        ]
        for prop, type_name in edge_props.items():
            columns.append((prop, _column_type(prop, type_name)))
        filter_indexes = shape.get("filter_indexes") or []
        edge_tables[label] = {
            "table": table,
            "src_col": src_col,
            "dst_col": dst_col,
            "columns": columns,
            "filter_indexes": filter_indexes,
        }

    return {"node_tables": node_tables, "edge_tables": edge_tables}


def _create_tables(conn: sqlite3.Connection, plan: dict) -> None:
    """Create all tables and indexes from a table plan."""
    cur = conn.cursor()
    for info in plan["node_tables"].values():
        col_defs = ", ".join(f"{c} {t}" for c, t in info["columns"])
        cur.execute(f"CREATE TABLE {info['table']} ({col_defs})")

    for info in plan["edge_tables"].values():
        col_defs = ", ".join(f"{c} {t}" for c, t in info["columns"])
        cur.execute(f"CREATE TABLE {info['table']} ({col_defs})")
        # Always index src and dst columns.
        cur.execute(
            f"CREATE INDEX idx_{info['table']}_{info['src_col']} "
            f"ON {info['table']}({info['src_col']})"
        )
        cur.execute(
            f"CREATE INDEX idx_{info['table']}_{info['dst_col']} "
            f"ON {info['table']}({info['dst_col']})"
        )
        # Additional user-declared composite indexes.
        for idx_cols in info["filter_indexes"]:
            col_list = "_".join(idx_cols)
            cur.execute(
                f"CREATE INDEX idx_{info['table']}_{col_list} "
                f"ON {info['table']}({', '.join(idx_cols)})"
            )
    conn.commit()


def _insert_nodes(conn: sqlite3.Connection, plan: dict, graph: PropertyGraph) -> None:
    """Insert all nodes from the graph into their SQLite tables."""
    cur = conn.cursor()
    for label, info in plan["node_tables"].items():
        col_names = [c for c, _ in info["columns"]]
        placeholders = ", ".join("?" * len(col_names))
        col_list = ", ".join(col_names)
        rows: list[tuple] = []
        for node in graph.nodes_by_label(label):
            row = []
            for col in col_names:
                val = node.props.get(col)
                if isinstance(val, (list, dict)):
                    val = json.dumps(val)
                rows.append(val)
            cur.execute(
                f"INSERT INTO {info['table']} ({col_list}) VALUES ({placeholders})",
                tuple(rows[-len(col_names):]),
            )
    conn.commit()


def _insert_edges(conn: sqlite3.Connection, plan: dict, graph: PropertyGraph) -> None:
    """Insert all edges from the graph into their SQLite tables."""
    cur = conn.cursor()
    for label, info in plan["edge_tables"].items():
        col_names = [c for c, _ in info["columns"]]
        placeholders = ", ".join("?" * len(col_names))
        col_list = ", ".join(col_names)
        src_col = info["src_col"]
        dst_col = info["dst_col"]
        prop_cols = [c for c, _ in info["columns"] if c not in (src_col, dst_col)]

        for edge in graph.edges_by_label(label):
            values = [edge.src, edge.dst]
            for col in prop_cols:
                val = edge.props.get(col)
                if isinstance(val, (list, dict)):
                    val = json.dumps(val)
                values.append(val)
            cur.execute(
                f"INSERT INTO {info['table']} ({col_list}) VALUES ({placeholders})",
                tuple(values),
            )
    conn.commit()


def build_mirror(
    graph: PropertyGraph,
    shapes_path: str | Path,
    db_path: str | Path,
) -> sqlite3.Connection:
    """Build a SQLite mirror of a PropertyGraph.

    Parameters
    ----------
    graph : PropertyGraph
        The in-memory graph to mirror.
    shapes_path : Path
        Path to a shapes.yaml file defining the ontology.
    db_path : Path
        Path for the output SQLite database (overwritten if it exists).

    Returns
    -------
    sqlite3.Connection
        Open connection to the new database.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    shapes = load_shapes(shapes_path)
    plan = _table_plan(shapes)
    conn = sqlite3.connect(str(db_path))
    _create_tables(conn, plan)
    _insert_nodes(conn, plan, graph)
    _insert_edges(conn, plan, graph)
    return conn
