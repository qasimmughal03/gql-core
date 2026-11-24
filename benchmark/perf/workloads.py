"""Workload definitions for GQL-Core Performance Benchmark v1, with a correctness oracle.

Every workload has:

* ``gql``: an openCypher query run with ``gql_core.run``, or ``plan``: a function returning a
  typed ``PlanBuilder`` plan run with ``gql_core.execute_plan``;
* ``oracle``: plain Python over the generator's records that computes the expected rows. It
  follows openCypher semantics (relationship uniqueness within a MATCH). It also serves as the
  "hand-written Python with ideal indexes" baseline;
* optional ``sqlite`` and ``networkx`` equivalents. Each is checked against the oracle before it
  is timed, so a baseline is only compared when it returns the same answer.

Rows are compared as tuples in the workload's column order; ``ordered`` says whether row order is
part of the answer (only where the query has a total ORDER BY).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

WORKLOAD_VERSION = "1.0"


# ── Oracle context: the generator's records with dict indexes ────────────────────────────


class Ctx:
    def __init__(self, data: dict[str, Any]):
        self.persons = {p["id"]: p for p in data["persons"]}
        self.companies = {c["id"]: c for c in data["companies"]}
        self.cities = {c["id"]: c for c in data["cities"]}
        self.knows: dict[str, list[str]] = defaultdict(list)
        for s, d in data["knows"]:
            self.knows[s].append(d)
        self.works = {p: c for p, c, _ in data["works_at"]}
        self.workers: dict[str, list[str]] = defaultdict(list)
        for p, c, _ in data["works_at"]:
            self.workers[c].append(p)
        self.lives = dict(data["lives_in"])
        self.located = dict(data["located_in"])
        self.parent = dict(data["subsidiary_of"])
        n_pers = len(data["persons"])
        comps = [c["id"] for c in data["companies"]]
        # Parameters, chosen deterministically from the data.
        self.lookup_id = f"p{n_pers // 2}"
        self.hub_id = "p0"
        self.typical_id = next(f"p{i}" for i in range(n_pers // 3, n_pers) if len(self.knows.get(f"p{i}", ())) == 4)
        self.leaf_id = next(c for c in reversed(comps) if c in self.parent)

    def params(self) -> dict[str, str]:
        return {"lookup": self.lookup_id, "hub": self.hub_id, "typical": self.typical_id, "leaf": self.leaf_id}

    def trail_ends(self, start: str, lo: int, hi: int) -> list[str]:
        """End nodes of every KNOWS trail (no repeated relationship) of length lo..hi from start."""
        out: list[str] = []

        def walk(node: str, depth: int, used: frozenset) -> None:
            if depth >= lo:
                out.append(node)
            if depth == hi:
                return
            for nxt in self.knows.get(node, ()):
                e = (node, nxt)  # no duplicate pairs, so (src, dst) identifies a relationship
                if e not in used:
                    walk(nxt, depth + 1, used | {e})

        walk(start, 0, frozenset())
        return out

    def ancestors(self, c: str) -> list[str]:
        out = []
        while c in self.parent:
            c = self.parent[c]
            out.append(c)
        return out


# ── Workload type ───────────────────────────────────────────────────────────────────────


@dataclass
class Workload:
    id: str
    category: str
    description: str
    cols: tuple[str, ...]
    oracle: Callable[[Ctx], list[tuple]]
    gql: str | None = None
    plan: Callable[[Ctx], Any] | None = None
    ordered: bool = False
    sqlite: str | None = None
    networkx: Callable[[Any, Ctx], list[tuple]] | None = None
    needs_inferred_graph: bool = False
    inference: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    def query_text(self, ctx: Ctx) -> str | None:
        return None if self.gql is None else self.gql.format(**ctx.params())

    def sql_text(self, ctx: Ctx) -> str | None:
        return None if self.sqlite is None else self.sqlite.format(**ctx.params())


def _r(x: float) -> float:
    return round(float(x), 6)


# ── Typed plans (imported lazily so this module stays engine-independent) ──────────────


def _plan_filter(ctx: Ctx):
    from gql_core import PlanBuilder, and_, eq, gt, lit, prop
    return (PlanBuilder.scan("p", "Person")
            .filter(and_(eq(prop("p", "age"), lit(42)), gt(prop("p", "score"), lit(0.9))))
            .project((prop("p", "id"), "id")).build())


def _plan_hop(ctx: Ctx):
    from gql_core import PlanBuilder, prop
    return (PlanBuilder.scan("p", "Person", id=ctx.typical_id)
            .expand("KNOWS", to_var="f", to_label="Person")
            .project((prop("f", "id"), "id")).build())


def _plan_at_least(ctx: Ctx):
    from gql_core import PlanBuilder, at_least_rel, prop
    return (PlanBuilder.scan("p", "Person").filter(at_least_rel(20, "p", "KNOWS", "f"))
            .project((prop("p", "id"), "id")).build())


def _plan_all(ctx: Ctx):
    from gql_core import PlanBuilder, all_rel, eq, prop
    return (PlanBuilder.scan("c", "Company")
            .filter(all_rel("c", "SUBSIDIARY_OF", "x", predicate=eq(prop("x", "industry"), prop("c", "industry"))))
            .project((prop("c", "id"), "id")).build())


# ── NetworkX equivalents (graphs built by baselines.build_networkx) ─────────────────────


def _nx_lookup(nxg, ctx):
    d = nxg["all"].nodes[ctx.lookup_id]
    return [(d["name"], d["age"])]


def _nx_count_company(nxg, ctx):
    return [(sum(1 for _, lbl in nxg["all"].nodes(data="label") if lbl == "Company"),)]


def _nx_hop(start):
    return lambda nxg, ctx: [(f,) for f in nxg["knows"].successors(getattr(ctx, start))]


def _nx_two_hop_distinct(nxg, ctx):
    k = nxg["knows"]
    return [(f,) for f in {f for a in k.successors(ctx.typical_id) for f in k.successors(a)}]


def _nx_var_len(nxg, ctx):
    import networkx as nx
    k, s = nxg["knows"], ctx.typical_id
    dist = nx.single_source_shortest_path_length(k, s, cutoff=3)
    reach = set(dist) - {s}
    if any(dist.get(u, 99) <= 2 for u in k.predecessors(s)):  # s is on a cycle of length <= 3
        reach.add(s)
    return [(len(reach),)]


def _nx_ancestors(nxg, ctx):
    import networkx as nx
    return [(a,) for a in nx.descendants(nxg["subsidiary"], ctx.leaf_id)]


def _nx_coworkers(nxg, ctx):
    w = nxg["works"]
    c = next(iter(w.successors(ctx.typical_id)))
    return [(sum(1 for b in w.predecessors(c) if b != ctx.typical_id),)]


def _nx_closure_pairs(nxg, ctx):
    import networkx as nx
    t = nxg["subsidiary"]
    return [(sum(len(nx.descendants(t, c)) - t.out_degree(c) for c in t.nodes),)]


# ── The workloads ───────────────────────────────────────────────────────────────────────


def _three_hop(ctx: Ctx) -> list[tuple]:
    return [(len(set(ctx.trail_ends(ctx.typical_id, 3, 3))),)]


WORKLOADS: list[Workload] = [
    Workload("W01_lookup", "exact property lookup", "one person by id (no property index: label scan + filter)",
             ("name", "age"),
             lambda c: [(c.persons[c.lookup_id]["name"], c.persons[c.lookup_id]["age"])],
             gql="MATCH (p:Person {{id: '{lookup}'}}) RETURN p.name AS name, p.age AS age",
             sqlite="SELECT name, age FROM person WHERE id = '{lookup}'", networkx=_nx_lookup),
    Workload("W02a_label_count", "label scan", "count every Company", ("n",),
             lambda c: [(len(c.companies),)],
             gql="MATCH (c:Company) RETURN count(c) AS n",
             sqlite="SELECT count(*) FROM company", networkx=_nx_count_company),
    Workload("W02b_label_rows", "label scan", "return every City id", ("id",),
             lambda c: [(i,) for i in c.cities],
             gql="MATCH (x:City) RETURN x.id AS id", sqlite="SELECT id FROM city"),
    Workload("W03a_filter_selective", "predicate filtering", "age = 42 AND score > 0.9 (about 0.16% of people)",
             ("id",),
             lambda c: [(p["id"],) for p in c.persons.values() if p["age"] == 42 and p["score"] > 0.9],
             gql="MATCH (p:Person) WHERE p.age = 42 AND p.score > 0.9 RETURN p.id AS id",
             sqlite="SELECT id FROM person WHERE age = 42 AND score > 0.9"),
    Workload("W03b_filter_broad_count", "predicate filtering", "age < 60 AND active, counted (about 53%)", ("n",),
             lambda c: [(sum(1 for p in c.persons.values() if p["age"] < 60 and p["active"]),)],
             gql="MATCH (p:Person) WHERE p.age < 60 AND p.active = true RETURN count(p) AS n",
             sqlite="SELECT count(*) FROM person WHERE age < 60 AND active = 1"),
    Workload("W03c_filter_broad_rows", "predicate filtering", "age < 60, every matching id returned (about 67%)",
             ("id",),
             lambda c: [(p["id"],) for p in c.persons.values() if p["age"] < 60],
             gql="MATCH (p:Person) WHERE p.age < 60 RETURN p.id AS id",
             sqlite="SELECT id FROM person WHERE age < 60"),
    Workload("W04a_hop_typical", "single-hop traversal", "people a typical person (out-degree 4) knows", ("id",),
             lambda c: [(f,) for f in c.knows[c.typical_id]],
             gql="MATCH (p:Person {{id: '{typical}'}})-[:KNOWS]->(f:Person) RETURN f.id AS id",
             sqlite="SELECT dst FROM knows WHERE src = '{typical}'", networkx=_nx_hop("typical_id")),
    Workload("W04b_hop_hub", "single-hop traversal", "people a hub (out-degree 300) knows", ("id",),
             lambda c: [(f,) for f in c.knows[c.hub_id]],
             gql="MATCH (p:Person {{id: '{hub}'}})-[:KNOWS]->(f:Person) RETURN f.id AS id",
             sqlite="SELECT dst FROM knows WHERE src = '{hub}'", networkx=_nx_hop("hub_id")),
    Workload("W05a_two_hop_distinct", "multi-hop traversal", "distinct friends-of-friends of a typical person",
             ("id",), lambda c: [(f,) for f in set(c.trail_ends(c.typical_id, 2, 2))],
             gql="MATCH (p:Person {{id: '{typical}'}})-[:KNOWS]->(:Person)-[:KNOWS]->(f:Person) RETURN DISTINCT f.id AS id",
             sqlite="SELECT DISTINCT k2.dst FROM knows k1 JOIN knows k2 ON k2.src = k1.dst WHERE k1.src = '{typical}'",
             networkx=_nx_two_hop_distinct),
    Workload("W05b_three_hop_count", "multi-hop traversal", "distinct people exactly three KNOWS hops away", ("n",),
             _three_hop,
             gql="MATCH (p:Person {{id: '{typical}'}})-[:KNOWS]->(:Person)-[:KNOWS]->(:Person)-[:KNOWS]->(f:Person) "
                 "RETURN count(DISTINCT f) AS n"),
    Workload("W06a_var_len_1_3", "variable-length path", "distinct people within 1..3 KNOWS hops", ("n",),
             lambda c: [(len(set(c.trail_ends(c.typical_id, 1, 3))),)],
             gql="MATCH (p:Person {{id: '{typical}'}})-[:KNOWS*1..3]->(f:Person) RETURN count(DISTINCT f) AS n",
             sqlite="WITH RECURSIVE r(n, d) AS (SELECT dst, 1 FROM knows WHERE src = '{typical}' "
                    "UNION SELECT k.dst, r.d + 1 FROM r JOIN knows k ON k.src = r.n WHERE r.d < 3) "
                    "SELECT count(DISTINCT n) FROM r",
             networkx=_nx_var_len),
    Workload("W06b_var_len_unbounded", "variable-length path", "every ancestor of a leaf company", ("id",),
             lambda c: [(a,) for a in c.ancestors(c.leaf_id)],
             gql="MATCH (c:Company {{id: '{leaf}'}})-[:SUBSIDIARY_OF*]->(r:Company) RETURN r.id AS id",
             sqlite="WITH RECURSIVE a(id) AS (SELECT parent FROM company WHERE id = '{leaf}' "
                    "UNION SELECT c.parent FROM a JOIN company c ON c.id = a.id WHERE c.parent IS NOT NULL) "
                    "SELECT id FROM a WHERE id IS NOT NULL",
             networkx=_nx_ancestors),
    Workload("W07a_join_coworkers", "multi-pattern join", "co-workers of a typical person (two comma patterns)",
             ("n",), lambda c: [(len(c.workers[c.works[c.typical_id]]) - 1,)],
             gql="MATCH (a:Person {{id: '{typical}'}})-[:WORKS_AT]->(c:Company), (b:Person)-[:WORKS_AT]->(c) "
                 "RETURN count(b) AS n",
             sqlite="SELECT count(*) FROM works_at w1 JOIN works_at w2 ON w2.company = w1.company "
                    "WHERE w1.person = '{typical}' AND w2.person <> w1.person",
             networkx=_nx_coworkers),
    Workload("W07b_join_full_graph", "multi-pattern join",
             "people who live in the city their employer is in (three patterns over the whole graph)", ("n",),
             lambda c: [(sum(1 for p, co in c.works.items() if c.lives[p] == c.located[co]),)],
             gql="MATCH (p:Person)-[:WORKS_AT]->(c:Company), (p)-[:LIVES_IN]->(x:City), (c)-[:LOCATED_IN]->(x) "
                 "RETURN count(p) AS n",
             sqlite="SELECT count(*) FROM works_at w JOIN person p ON p.id = w.person "
                    "JOIN company c ON c.id = w.company WHERE p.city = c.city"),
    Workload("W08a_group_industry", "aggregation and grouping", "employees and mean age per industry",
             ("industry", "n", "avg_age"),
             lambda c: sorted(
                 (ind, len(ages), _r(sum(ages) / len(ages)))
                 for ind, ages in _group(((c.companies[co]["industry"], c.persons[p]["age"]) for p, co in c.works.items())).items()),
             gql="MATCH (p:Person)-[:WORKS_AT]->(c:Company) RETURN c.industry AS industry, count(p) AS n, "
                 "avg(p.age) AS avg_age ORDER BY industry ASC",
             ordered=True,
             sqlite="SELECT c.industry, count(*), avg(p.age) FROM works_at w JOIN person p ON p.id = w.person "
                    "JOIN company c ON c.id = w.company GROUP BY c.industry ORDER BY c.industry"),
    Workload("W08b_group_city_top5", "aggregation and grouping", "five most populous cities (tie-broken by id)",
             ("city", "n"),
             lambda c: sorted(((k, len(v)) for k, v in _group((city, p) for p, city in c.lives.items()).items()),
                              key=lambda t: (-t[1], t[0]))[:5],
             gql="MATCH (p:Person)-[:LIVES_IN]->(x:City) RETURN x.id AS city, count(p) AS n "
                 "ORDER BY n DESC, city ASC LIMIT 5",
             ordered=True,
             sqlite="SELECT city, count(*) AS n FROM person GROUP BY city ORDER BY n DESC, city ASC LIMIT 5"),
    Workload("W09_sort_limit", "sorting and limits", "top 10 people by score (scores are unique)", ("id", "score"),
             lambda c: [(p["id"], p["score"]) for p in sorted(c.persons.values(), key=lambda p: -p["score"])[:10]],
             gql="MATCH (p:Person) RETURN p.id AS id, p.score AS score ORDER BY score DESC LIMIT 10",
             ordered=True, sqlite="SELECT id, score FROM person ORDER BY score DESC LIMIT 10"),
    Workload("W10a_exists", "correlated existence", "companies employing at least one 25-year-old", ("n",),
             lambda c: [(sum(1 for co, ws in c.workers.items() if any(c.persons[p]["age"] == 25 for p in ws)),)],
             gql="MATCH (c:Company) WHERE EXISTS {{ (c)<-[:WORKS_AT]-(:Person {{age: 25}}) }} RETURN count(c) AS n",
             sqlite="SELECT count(*) FROM company c WHERE EXISTS (SELECT 1 FROM works_at w JOIN person p "
                    "ON p.id = w.person WHERE w.company = c.id AND p.age = 25)"),
    Workload("W10b_not_exists", "correlated existence", "people who know nobody (negated pattern predicate)", ("n",),
             lambda c: [(sum(1 for p in c.persons if not c.knows.get(p)),)],
             gql="MATCH (p:Person) WHERE NOT (p)-[:KNOWS]->(:Person) RETURN count(p) AS n",
             sqlite="SELECT count(*) FROM person p WHERE NOT EXISTS (SELECT 1 FROM knows k WHERE k.src = p.id)"),
    Workload("W11a_at_least", "quantified relationship predicate", "people who know at least 20 people (typed plan)",
             ("id",), lambda c: [(p,) for p in c.persons if len(c.knows.get(p, ())) >= 20],
             plan=_plan_at_least,
             sqlite="SELECT src FROM knows GROUP BY src HAVING count(*) >= 20"),
    Workload("W11b_all", "quantified relationship predicate",
             "companies whose every parent shares their industry (vacuously true for roots; typed plan)", ("id",),
             lambda c: [(co,) for co in c.companies
                        if co not in c.parent or c.companies[c.parent[co]]["industry"] == c.companies[co]["industry"]],
             plan=_plan_all,
             sqlite="SELECT c.id FROM company c LEFT JOIN company p ON p.id = c.parent "
                    "WHERE c.parent IS NULL OR p.industry = c.industry"),
    Workload("W12a_typed_filter", "typed-plan execution", "typed-plan version of W03a", ("id",),
             lambda c: [(p["id"],) for p in c.persons.values() if p["age"] == 42 and p["score"] > 0.9],
             plan=_plan_filter, tags=("pair:W03a_filter_selective",)),
    Workload("W12b_typed_hop", "typed-plan execution", "typed-plan version of W04a", ("id",),
             lambda c: [(f,) for f in c.knows[c.typical_id]], plan=_plan_hop, tags=("pair:W04a_hop_typical",)),
    Workload("W13_transitive_inference", "ontology transitive inference",
             "derive every indirect SUBSIDIARY_OF pair with InferenceEngine (whole graph as facts)", ("derived",),
             lambda c: [(sum(max(0, len(c.ancestors(co)) - 1) for co in c.companies),)],
             inference=True,
             sqlite="WITH RECURSIVE a(c, anc, d) AS (SELECT id, parent, 1 FROM company WHERE parent IS NOT NULL "
                    "UNION ALL SELECT a.c, p.parent, a.d + 1 FROM a JOIN company p ON p.id = a.anc "
                    "WHERE p.parent IS NOT NULL) SELECT count(*) FROM a WHERE d >= 2",
             networkx=_nx_closure_pairs),
    Workload("W14a_derived_query", "derived relation query",
             "ultimate parent of a leaf company over materialized SUBSIDIARY_OF edges", ("id",),
             lambda c: [(c.ancestors(c.leaf_id)[-1],)],
             gql="MATCH (c:Company {{id: '{leaf}'}})-[:SUBSIDIARY_OF]->(r:Company) "
                 "WHERE NOT (r)-[:SUBSIDIARY_OF]->(:Company) RETURN r.id AS id",
             needs_inferred_graph=True, tags=("pair:W14b_derived_via_var_len",)),
    Workload("W14b_derived_via_var_len", "derived relation query",
             "the same answer with a variable-length path on the base graph", ("id",),
             lambda c: [(c.ancestors(c.leaf_id)[-1],)],
             gql="MATCH (c:Company {{id: '{leaf}'}})-[:SUBSIDIARY_OF*]->(r:Company) "
                 "WHERE NOT (r)-[:SUBSIDIARY_OF]->(:Company) RETURN r.id AS id"),
]


def _group(pairs) -> dict[Any, list]:
    out: dict[Any, list] = defaultdict(list)
    for k, v in pairs:
        out[k].append(v)
    return out


def normalize(rows: list[tuple], ordered: bool) -> list[tuple]:
    def val(v):
        if isinstance(v, float):
            return round(v, 6)
        if isinstance(v, bool):
            return int(v)
        return v
    norm = [tuple(val(v) for v in r) for r in rows]
    return norm if ordered else sorted(norm, key=repr)


def gql_rows(rows: list[dict], cols: tuple[str, ...]) -> list[tuple]:
    return [tuple(r.get(c) for c in cols) for r in rows]
