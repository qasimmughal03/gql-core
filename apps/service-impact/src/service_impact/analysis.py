"""Impact analysis over the catalog graph with GQL-Core.

Two independent mechanisms answer "what is affected if X fails?":

* **Inference.** Each stored runtime relationship (CALLS, READS_FROM, ...) implies
  ``RELIES_ON``; ``RELIES_ON`` is transitive. ``InferenceEngine`` derives every ``RELIES_ON``
  pair and keeps, for each one, the facts it was derived from, so the answer can say which
  relationships were stored in the catalog and which were inferred, and by which rule.
* **Query.** A variable-length openCypher path over the stored relationships finds the shortest
  dependency path from each affected component to the failed one: the evidence shown to users.

:meth:`ImpactAnalyzer.impact` checks that both give the same set of components.

GQL-Core 0.2.0a4's ``run()`` takes no query parameters, so ids are checked against the graph
(and against a strict pattern) before they are placed in query text.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from gql_core import (
    Atom,
    Edge,
    InferenceEngine,
    InferenceRule,
    PlanBuilder,
    PropertyGraph,
    at_least_rel,
    col,
    eq,
    execute_plan,
    lit,
    make_transitive_rule,
    prop,
    run,
    validate_logical_plan,
)

from service_impact.catalog import ID_RE, RUNTIME_RELATIONS, build_graph, load_catalog

RELIES_ON = "RELIES_ON"
_RUNTIME = "|".join(RUNTIME_RELATIONS)
MAX_PATH = 10


class UnknownComponent(KeyError):
    pass


@dataclass
class Step:
    src: str
    rel: str
    dst: str


@dataclass
class Affected:
    id: str
    name: str
    kind: str
    tier: int | None
    team: str | None
    team_lead: str | None
    channel: str | None
    dependency: str                     # "direct" (a stored relationship) or "indirect" (inferred)
    hops: int                           # length of the shortest stored path
    evidence_path: list[Step]           # that shortest path, from the openCypher query
    derived_by: list[str] = field(default_factory=list)  # inference rules behind RELIES_ON
    derivation: list[Step] = field(default_factory=list)  # stored facts the inference used


def runtime_rules() -> list[InferenceRule]:
    rules = [InferenceRule(name=f"{r.lower()}_implies_relies_on",
                           head=Atom("rel", ("?a", RELIES_ON, "?b")),
                           body=(Atom("rel", ("?a", r, "?b")),),
                           description=f"{r}(a, b) means a stops working when b fails")
             for r in RUNTIME_RELATIONS]
    return rules + [make_transitive_rule(RELIES_ON)]


def _leaves(fact) -> list:
    """The stored facts at the bottom of a derived fact's evidence tree, in path order."""
    if not fact.is_inferred:
        return [fact]
    out = []
    for e in fact.evidence:
        out.extend(_leaves(e))
    return out


def _rules(fact) -> list[str]:
    if not fact.is_inferred:
        return []
    names = [fact.rule_name]
    for e in fact.evidence:
        names.extend(n for n in _rules(e) if n not in names)
    return names


class ImpactAnalyzer:
    def __init__(self, graph: PropertyGraph):
        self.graph = graph
        # The default max_facts (250,000) also counts the graph's stored facts; set it explicitly so
        # a larger catalog cannot cut inference short.
        engine = InferenceEngine(max_facts=5_000_000)
        for rule in runtime_rules():
            engine.add_rule(rule)
        _, derived = engine.infer(graph)
        self.derived = {(f.args[0], f.args[2]): f for f in derived if f.predicate == "rel" and f.args[1] == RELIES_ON}
        # Materialize the derived RELIES_ON edges so queries can use them; they are marked is_inferred.
        for (src, dst), f in self.derived.items():
            graph.add_edge(Edge(id=f"inf-{src}-{RELIES_ON}-{dst}", label=RELIES_ON, src=src, dst=dst,
                                props={"is_inferred": True, "inferred_by": f.rule_name}))

    @classmethod
    def from_catalog(cls, path=None) -> ImpactAnalyzer:
        return cls(build_graph(load_catalog(path)))

    # ── helpers ──────────────────────────────────────────────────────────────────────

    def _check(self, cid: str, labels: tuple[str, ...] | None = None) -> None:
        node = self.graph.get_node(cid) if ID_RE.match(cid or "") else None
        if node is None or node.label in ("Team", "Person"):
            raise UnknownComponent(cid)
        if labels and node.label not in labels:
            raise UnknownComponent(f"{cid} is a {node.label}, expected {' or '.join(labels)}")

    def components(self) -> list[dict[str, Any]]:
        return run("MATCH (c) WHERE c.kind IS NOT NULL "
                   "OPTIONAL MATCH (c)-[:OWNED_BY]->(t:Team) "
                   "RETURN c.id AS id, c.name AS name, c.kind AS kind, c.tier AS tier, t.name AS team "
                   "ORDER BY id", self.graph)

    def owners(self) -> dict[str, dict[str, Any]]:
        rows = run("MATCH (c)-[:OWNED_BY]->(t:Team) OPTIONAL MATCH (p:Person)-[:LEADS]->(t) "
                   "RETURN c.id AS id, t.name AS team, t.channel AS channel, p.name AS lead", self.graph)
        return {r["id"]: r for r in rows}

    # ── questions ────────────────────────────────────────────────────────────────────

    def dependents_of_database(self, db_id: str) -> list[dict[str, Any]]:
        """Components with a stored READS_FROM, WRITES_TO or DEPENDS_ON relationship to the database."""
        self._check(db_id, ("Database",))
        return run(f"MATCH (c)-[r:READS_FROM|WRITES_TO|DEPENDS_ON]->(d:Database {{id: '{db_id}'}}) "
                   "RETURN c.id AS id, c.name AS name, collect(type(r)) AS access ORDER BY id", self.graph)

    def impact(self, failed: str) -> list[Affected]:
        """Every component that stops working if ``failed`` fails, with owner and evidence."""
        self._check(failed)
        inferred = run(f"MATCH (c)-[r:{RELIES_ON}]->(f {{id: '{failed}'}}) WHERE c.id <> '{failed}' "
                       "RETURN c.id AS id", self.graph)
        paths = run(f"MATCH p = (c)-[:{_RUNTIME}*1..{MAX_PATH}]->(f {{id: '{failed}'}}) WHERE c.id <> '{failed}' "
                    "RETURN c.id AS id, c.name AS name, c.kind AS kind, c.tier AS tier, "
                    "[n IN nodes(p) | n.id] AS ids, [r IN relationships(p) | type(r)] AS rels", self.graph)
        shortest: dict[str, dict[str, Any]] = {}
        for row in paths:
            best = shortest.get(row["id"])
            key = (len(row["rels"]), row["ids"])
            if best is None or key < (len(best["rels"]), best["ids"]):
                shortest[row["id"]] = row
        by_inference = {r["id"] for r in inferred}
        if by_inference != set(shortest):
            raise AssertionError(f"inference and path query disagree: {sorted(by_inference ^ set(shortest))}")

        owners = self.owners()
        out = []
        for cid, row in shortest.items():
            fact = self.derived[(cid, failed)]
            own = owners.get(cid, {})
            hops = len(row["rels"])
            out.append(Affected(
                id=cid, name=row["name"], kind=row["kind"], tier=row["tier"],
                team=own.get("team"), team_lead=own.get("lead"), channel=own.get("channel"),
                dependency="direct" if hops == 1 else "indirect", hops=hops,
                evidence_path=[Step(a, r, b) for a, r, b in zip(row["ids"], row["rels"], row["ids"][1:])],
                derived_by=_rules(fact),
                derivation=[Step(*leaf.args) for leaf in _leaves(fact)],
            ))
        return sorted(out, key=lambda a: (a.tier if a.tier is not None else 99, a.hops, a.id))

    def teams_to_notify(self, failed: str) -> list[dict[str, Any]]:
        self._check(failed)
        return run(f"MATCH (c)-[:{RELIES_ON}]->(f {{id: '{failed}'}}), (c)-[:OWNED_BY]->(t:Team) "
                   f"WHERE c.id <> '{failed}' "
                   "RETURN t.name AS team, t.channel AS channel, count(c) AS components, "
                   "collect(c.id) AS affected ORDER BY components DESC, team ASC", self.graph)

    def unowned_affected(self, failed: str) -> list[str]:
        self._check(failed)
        rows = run(f"MATCH (c)-[:{RELIES_ON}]->(f {{id: '{failed}'}}) "
                   f"WHERE c.id <> '{failed}' AND NOT (c)-[:OWNED_BY]->(:Team) RETURN c.id AS id ORDER BY id",
                   self.graph)
        return [r["id"] for r in rows]

    # ── typed plans: the structured form an agent or a UI can build without writing a query ──

    def fan_out_hotspots(self, min_calls: int = 3) -> list[dict[str, Any]]:
        """Services that call at least ``min_calls`` components: an AT_LEAST quantified predicate."""
        plan = (PlanBuilder.scan("s", "Service")
                .filter(at_least_rel(min_calls, "s", "CALLS", "x"))
                .project((prop("s", "id"), "id"), (prop("s", "name"), "name"))
                .sort((col("id"), "ASC")).build())
        report = validate_logical_plan(plan, strict=True)
        if not report.is_valid:
            raise report.errors[0]
        return execute_plan(plan, self.graph)["rows"]

    def tier_owners_plan(self, tier: int):
        return (PlanBuilder.scan("s", "Service")
                .filter(eq(prop("s", "tier"), lit(tier)))
                # from_var must be given after a filter: 0.2.0a4's builder infers it only directly
                # after scan() or expand(), and otherwise falls back to "a", which validation rejects.
                .expand("OWNED_BY", to_var="t", to_label="Team", from_var="s")
                .project((prop("s", "id"), "service"), (prop("t", "name"), "team"))
                .sort((col("service"), "ASC")).build())

    def tier_owners(self, tier: int = 1) -> list[dict[str, Any]]:
        """Owning team of every service in a tier, as a typed, validated plan."""
        return execute_plan(self.tier_owners_plan(tier), self.graph)["rows"]


def as_dict(a: Affected) -> dict[str, Any]:
    return asdict(a)
