"""Deterministic synthetic graphs for GQL-Core Performance Benchmark v1.

The generator is plain Python and never imports ``gql_core``: the same records feed GQL-Core,
SQLite, NetworkX and the hand-written Python oracle, so every system answers over identical data.

Schema
    (:Person {id, name, age, score, active})    about 91% of nodes
    (:Company {id, name, industry, size})       about 8.3% of nodes
    (:City {id, name})                          about 0.2% of nodes (at least 10)

    (Person)-[:KNOWS]->(Person)             skewed: low-numbered people are popular targets,
                                            p0..p4 are high out-degree "hubs"; no self-loops,
                                            no duplicate pairs
    (Person)-[:WORKS_AT {since}]->(Company)  exactly one per person
    (Person)-[:LIVES_IN]->(City)             exactly one per person
    (Company)-[:LOCATED_IN]->(City)          exactly one per company
    (Company)-[:SUBSIDIARY_OF]->(Company)    a forest: company i reports to company (i-1)//4,
                                            except every tenth company, which is a root

``score`` is a permutation of ``k / persons``, so it is unique and ORDER BY score has no ties.
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Any

GENERATOR_VERSION = "1.0"
INDUSTRIES = ("energy", "finance", "health", "logistics", "media", "retail", "software", "telecom")
HUBS = 5
HUB_OUT_DEGREE = 300


def generate(total_nodes: int, seed: int = 42) -> dict[str, Any]:
    rng = random.Random(seed)
    n_city = max(10, total_nodes // 500)
    n_comp = max(20, total_nodes // 12)
    n_pers = total_nodes - n_city - n_comp

    cities = [{"id": f"city{i}", "name": f"City {i}"} for i in range(n_city)]
    companies = [{"id": f"c{i}", "name": f"Company {i}", "industry": INDUSTRIES[rng.randrange(8)],
                  "size": rng.randrange(10, 10_000)} for i in range(n_comp)]
    perm = list(range(n_pers))
    rng.shuffle(perm)
    persons = [{"id": f"p{i}", "name": f"Person {i}", "age": 18 + rng.randrange(63),
                "score": perm[i] / n_pers, "active": rng.random() < 0.8} for i in range(n_pers)]

    knows: list[tuple[str, str]] = []
    for i in range(n_pers):
        deg = HUB_OUT_DEGREE if i < HUBS else min(int(rng.expovariate(1 / 4.0)), 200)
        targets: set[int] = set()
        attempts = 0
        while len(targets) < deg and attempts < deg * 4:
            attempts += 1
            t = int(n_pers * rng.random() ** 3)  # skew towards low ids: popular people
            if t != i:
                targets.add(t)
        knows.extend((f"p{i}", f"p{t}") for t in sorted(targets))

    works_at = [(p["id"], f"c{rng.randrange(n_comp)}", 1990 + rng.randrange(35)) for p in persons]
    lives_in = [(p["id"], f"city{rng.randrange(n_city)}") for p in persons]
    located_in = [(c["id"], f"city{rng.randrange(n_city)}") for c in companies]
    subsidiary_of = [(f"c{i}", f"c{(i - 1) // 4}") for i in range(1, n_comp) if i % 10]

    return {
        "meta": {"generator_version": GENERATOR_VERSION, "seed": seed, "total_nodes": total_nodes},
        "persons": persons, "companies": companies, "cities": cities,
        "knows": knows, "works_at": works_at, "lives_in": lives_in,
        "located_in": located_in, "subsidiary_of": subsidiary_of,
    }


def describe(data: dict[str, Any]) -> dict[str, Any]:
    """Sizes, label distribution and degree distribution, for the results file."""
    out_deg = Counter(s for s, _ in data["knows"])
    in_deg = Counter(d for _, d in data["knows"])
    persons = [p["id"] for p in data["persons"]]

    def dist(counter: Counter) -> dict[str, float]:
        vals = sorted(counter.get(p, 0) for p in persons)
        q = lambda f: vals[min(len(vals) - 1, int(f * len(vals)))]  # noqa: E731
        return {"mean": round(sum(vals) / len(vals), 3), "median": q(0.5), "p90": q(0.9),
                "p99": q(0.99), "max": vals[-1], "zero": sum(1 for v in vals if v == 0)}

    edges = {k: len(data[k]) for k in ("knows", "works_at", "lives_in", "located_in", "subsidiary_of")}
    labels = {"Person": len(data["persons"]), "Company": len(data["companies"]), "City": len(data["cities"])}
    return {
        **data["meta"],
        "nodes": sum(labels.values()), "edges": sum(edges.values()),
        "nodes_by_label": labels,
        "edges_by_type": {k.upper(): v for k, v in edges.items()},
        "knows_out_degree": dist(out_deg),
        "knows_in_degree": dist(in_deg),
    }


def to_graph_dict(data: dict[str, Any]) -> dict[str, Any]:
    """The flat ``{"nodes": [...], "edges": [...]}`` form ``PropertyGraph.from_dict`` reads."""
    nodes = ([{"label": "Person", **p} for p in data["persons"]]
             + [{"label": "Company", **c} for c in data["companies"]]
             + [{"label": "City", **c} for c in data["cities"]])
    edges: list[dict[str, Any]] = []
    add = edges.append
    for i, (s, d) in enumerate(data["knows"]):
        add({"id": f"k{i}", "label": "KNOWS", "src": s, "dst": d})
    for i, (s, d, since) in enumerate(data["works_at"]):
        add({"id": f"w{i}", "label": "WORKS_AT", "src": s, "dst": d, "since": since})
    for i, (s, d) in enumerate(data["lives_in"]):
        add({"id": f"l{i}", "label": "LIVES_IN", "src": s, "dst": d})
    for i, (s, d) in enumerate(data["located_in"]):
        add({"id": f"li{i}", "label": "LOCATED_IN", "src": s, "dst": d})
    for i, (s, d) in enumerate(data["subsidiary_of"]):
        add({"id": f"s{i}", "label": "SUBSIDIARY_OF", "src": s, "dst": d})
    return {"nodes": nodes, "edges": edges}
