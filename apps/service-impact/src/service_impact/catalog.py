"""Load a service catalog and turn it into a GQL-Core property graph.

The catalog is this application's own format (see ``data/catalog.json``): teams, and components
that list what they call, read from, write to, depend on and are deployed on. It is validated
before any graph is built, so a typo in an id is reported instead of becoming a dangling edge.

Graph model
    (:Service|Database|API|Queue|Deployment {id, name, tier, kind})
    (:Team {id, name, channel})   (:Person {id, name})
    (component)-[:CALLS|READS_FROM|WRITES_TO|DEPENDS_ON|DEPLOYED_ON]->(component)
    (component)-[:OWNED_BY]->(:Team)      (:Person)-[:LEADS]->(:Team)
"""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path
from typing import Any

from gql_core import Edge, Node, PropertyGraph

KINDS = {"service": "Service", "database": "Database", "api": "API", "queue": "Queue", "deployment": "Deployment"}
RELATIONS = {"calls": "CALLS", "reads_from": "READS_FROM", "writes_to": "WRITES_TO",
             "depends_on": "DEPENDS_ON", "deployed_on": "DEPLOYED_ON"}
# Every relationship above means "the source stops working if the target fails".
RUNTIME_RELATIONS = tuple(RELATIONS.values())
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class CatalogError(ValueError):
    """The catalog is malformed; ``problems`` lists every problem found."""

    def __init__(self, problems: list[str]):
        super().__init__("invalid catalog:\n  " + "\n  ".join(problems))
        self.problems = problems


def default_catalog_path() -> Path:
    return Path(str(resources.files("service_impact") / "data" / "catalog.json"))


def load_catalog(path: str | Path | None = None) -> dict[str, Any]:
    raw = json.loads(Path(path or default_catalog_path()).read_text(encoding="utf-8"))
    validate_catalog(raw)
    return raw


def validate_catalog(cat: dict[str, Any]) -> None:
    problems: list[str] = []
    teams = {t.get("id") for t in cat.get("teams", [])}
    ids: set[str] = set()
    for t in cat.get("teams", []):
        if not ID_RE.match(str(t.get("id", ""))):
            problems.append(f"team id {t.get('id')!r} must match {ID_RE.pattern}")
    for c in cat.get("components", []):
        cid = c.get("id")
        if not ID_RE.match(str(cid or "")):
            problems.append(f"component id {cid!r} must match {ID_RE.pattern}")
        if cid in ids or cid in teams:
            problems.append(f"duplicate id {cid!r}")
        ids.add(cid)
        if c.get("kind") not in KINDS:
            problems.append(f"{cid}: unknown kind {c.get('kind')!r} (expected one of {sorted(KINDS)})")
        if c.get("owner") is not None and c["owner"] not in teams:
            problems.append(f"{cid}: owner {c['owner']!r} is not a team")
        unknown = set(c) - {"id", "kind", "name", "tier", "owner", *RELATIONS}
        if unknown:
            problems.append(f"{cid}: unknown fields {sorted(unknown)}")
    for c in cat.get("components", []):
        for field, rel in RELATIONS.items():
            for target in c.get(field, []):
                if target not in ids:
                    problems.append(f"{c.get('id')}: {field} refers to unknown component {target!r}")
                elif target == c.get("id"):
                    problems.append(f"{c.get('id')}: {field} refers to itself")
    if problems:
        raise CatalogError(problems)


def build_graph(cat: dict[str, Any]) -> PropertyGraph:
    graph = PropertyGraph()
    for t in cat["teams"]:
        graph.add_node(Node(id=t["id"], label="Team",
                            props={"id": t["id"], "name": t["name"], "channel": t.get("channel")}))
        if t.get("lead"):
            pid = "person-" + re.sub(r"[^a-z0-9]+", "-", t["lead"].lower()).strip("-")
            graph.add_node(Node(id=pid, label="Person", props={"id": pid, "name": t["lead"]}))
            graph.add_edge(Edge(id=f"{pid}-leads-{t['id']}", label="LEADS", src=pid, dst=t["id"], props={}))
    for c in cat["components"]:
        graph.add_node(Node(id=c["id"], label=KINDS[c["kind"]],
                            props={"id": c["id"], "name": c.get("name", c["id"]), "tier": c.get("tier"),
                                   "kind": c["kind"]}))
    for c in cat["components"]:
        for field, rel in RELATIONS.items():
            for target in c.get(field, []):
                graph.add_edge(Edge(id=f"{c['id']}-{rel}-{target}", label=rel, src=c["id"], dst=target,
                                    props={"source": "catalog"}))
        if c.get("owner"):
            graph.add_edge(Edge(id=f"{c['id']}-owned-by", label="OWNED_BY", src=c["id"], dst=c["owner"], props={}))
    return graph
