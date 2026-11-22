"""Load a CypherBench SimpleKG JSON file into a GQL-Core PropertyGraph.

Mirrors the official SimpleKG -> Neo4j import: every entity becomes a node
with its label, a ``name`` property and its typed properties; every relation
becomes an edge with its properties. Properties declared ``date`` in the
schema are converted to openCypher ``date`` values so that comparisons with
``date('...')`` and ORDER BY behave as in Neo4j.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from gql_core.graph import Edge, Node, PropertyGraph
from gql_core.query.cypher_temporal import CypherTemporalValue, _date_to_props, _format_date

_DATE_RE = re.compile(r"^(-?\d{1,4})-(\d{2})-(\d{2})$")


def _to_date(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    m = _DATE_RE.match(value)
    if not m:
        return value
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return CypherTemporalValue(_format_date(y, mo, d), _date_to_props(y, mo, d), kind="date")
    except ValueError:
        return value


def _date_props(schema: dict) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    ent = {e["label"]: {k for k, t in e["properties"].items() if t == "date"} for e in schema["entities"]}
    rel = {r["label"]: {k for k, t in r["properties"].items() if t == "date"} for r in schema["relations"]}
    return ent, rel


def load_simplekg(path: Path) -> tuple[PropertyGraph, dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    schema = data["schema"]
    ent_dates, rel_dates = _date_props(schema)

    graph = PropertyGraph()
    for e in data["entities"]:
        props = {"name": e["name"]}
        dates = ent_dates.get(e["label"], ())
        for k, v in e["properties"].items():
            props[k] = _to_date(v) if k in dates else v
        graph.add_node(Node(e["eid"], e["label"], props))

    for r in data["relations"]:
        dates = rel_dates.get(r["label"], ())
        props = {k: (_to_date(v) if k in dates else v) for k, v in r["properties"].items()}
        graph.add_edge(Edge(f"r{r['rid']}", r["label"], r["subj_id"], r["obj_id"], props))
    del data
    return graph, schema
