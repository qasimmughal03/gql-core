"""GQL-Core engine check on real Hetionet v1.0 data (Himmelstein et al., eLife 2017).

This is our own evaluation on a real dataset, not a published benchmark: every
answer GQL-Core produces is compared with the answer computed independently in
plain Python from the raw Hetionet TSV/SIF files. A query passes only if the two
agree; the script exits non-zero if anything fails.

Data slice: all CbG (Compound binds Gene), CtD (Compound treats Disease) and
DaG (Disease associates Gene) edges of Hetionet v1.0.

Checks
  * five Cypher queries (lookup, aggregation, 2-hop metapath, shared targets,
    disease gene footprint), each against an independent Python computation;
  * one Datalog rule, CbG(c, g) AND DaG(d, g) => POTENTIALLY_TREATS(c, d)
    (the Compound-binds-Gene-associated-with-Disease metapath), whose derived
    facts must equal the independent join.

Natural-language evaluation is done by the CypherBench and MetaQA harnesses
(benchmark/cypherbench, benchmark/metaqa), not here.
"""

from __future__ import annotations

import gzip
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from benchmark.industry.download_datasets import download_hetionet
from gql_core import Edge, Node, PropertyGraph, run
from gql_core.inference import InferenceEngine
from gql_core.inference.rules import Atom, InferenceRule

TARGET_RELS = {"CbG", "CtD", "DaG"}
OUT = Path("benchmark/results/full_hetionet_benchmark.json")


def load_slice(nodes_file: Path, edges_file: Path) -> tuple[dict[str, dict], list[tuple[str, str, str]]]:
    nodes: dict[str, dict] = {}
    with open(nodes_file, encoding="utf-8") as f:
        f.readline()
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3:
                nodes[parts[0]] = {"name": parts[1], "kind": parts[2]}
    edges: list[tuple[str, str, str]] = []
    with gzip.open(edges_file, "rt", encoding="utf-8") as f:
        f.readline()
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3 and parts[1] in TARGET_RELS:
                edges.append((parts[0], parts[1], parts[2]))
    return nodes, edges


def build_graph(nodes: dict[str, dict], edges: list[tuple[str, str, str]]) -> PropertyGraph:
    graph = PropertyGraph()
    used = {n for s, _, d in edges for n in (s, d)}
    for nid in used:
        meta = nodes[nid]
        graph.add_node(Node(nid, meta["kind"].replace(" ", ""), {"name": meta["name"], "het_id": nid}))
    for i, (s, r, d) in enumerate(edges):
        graph.add_edge(Edge(f"e{i}", r, s, d))
    return graph


# ── Independent ground truth (plain Python over the raw edge list) ─────────────

class Truth:
    def __init__(self, nodes: dict[str, dict], edges: list[tuple[str, str, str]]) -> None:
        self.name = {k: v["name"] for k, v in nodes.items()}
        self.by_rel: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for s, r, d in edges:
            self.by_rel[r].append((s, d))

    def ids_named(self, name: str, prefix: str) -> set[str]:
        return {k for k, v in self.name.items() if v == name and k.startswith(prefix)}

    def diseases_treated_by(self, compound: str) -> list[str]:
        cs = self.ids_named(compound, "Compound::")
        return sorted(self.name[d] for c, d in self.by_rel["CtD"] if c in cs)

    def count_by_source(self, rel: str) -> Counter:
        return Counter(self.name[s] for s, _ in self.by_rel[rel])

    def drugs_binding_genes_of(self, disease: str) -> set[tuple[str, str]]:
        ds = self.ids_named(disease, "Disease::")
        genes = {g for d, g in self.by_rel["DaG"] if d in ds}
        return {(self.name[c], self.name[g]) for c, g in self.by_rel["CbG"] if g in genes}

    def shared_targets(self, a: str, b: str) -> list[str]:
        ga = {g for c, g in self.by_rel["CbG"] if c in self.ids_named(a, "Compound::")}
        gb = {g for c, g in self.by_rel["CbG"] if c in self.ids_named(b, "Compound::")}
        return sorted(self.name[g] for g in ga & gb)

    def metapath_cbg_dag(self) -> set[tuple[str, str]]:
        diseases_of_gene: dict[str, set[str]] = defaultdict(set)
        for d, g in self.by_rel["DaG"]:
            diseases_of_gene[g].add(d)
        return {(c, d) for c, g in self.by_rel["CbG"] for d in diseases_of_gene.get(g, ())}


def topk_ok(rows: list[dict], key: str, val: str, counts: Counter, k: int) -> tuple[bool, str]:
    """Top-k with ties: the returned counts must be exactly the k largest, and each pair correct."""
    expected = sorted(counts.values(), reverse=True)[:k]
    got = [r[val] for r in rows]
    if got != expected:
        return False, f"counts {got} != expected top-{k} {expected}"
    for r in rows:
        if counts.get(r[key]) != r[val]:
            return False, f"{r[key]} has {counts.get(r[key])}, engine said {r[val]}"
    return True, "top-k counts and every (name, count) pair match"


def main() -> int:
    nodes_file, edges_file = download_hetionet()
    t0 = time.perf_counter()
    nodes, edges = load_slice(nodes_file, edges_file)
    graph = build_graph(nodes, edges)
    truth = Truth(nodes, edges)
    rel_counts = Counter(r for _, r, _ in edges)
    print(f"Hetionet v1.0 slice: {len(graph._nodes):,} nodes, {len(edges):,} edges {dict(rel_counts)} "
          f"loaded in {time.perf_counter() - t0:.1f}s")

    checks: list[tuple[str, str, Callable[[list[dict]], tuple[bool, str]]]] = [
        ("HET-01 lookup",
         'MATCH (c:Compound {name: "Reserpine"})-[:CtD]->(d:Disease) RETURN d.name AS disease ORDER BY disease',
         lambda rows: ([r["disease"] for r in rows] == truth.diseases_treated_by("Reserpine"),
                       f"expected {truth.diseases_treated_by('Reserpine')}")),
        ("HET-02 top-5 compounds by bound genes",
         "MATCH (c:Compound)-[:CbG]->(g:Gene) RETURN c.name AS drug, count(g) AS n ORDER BY n DESC LIMIT 5",
         lambda rows: topk_ok(rows, "drug", "n", truth.count_by_source("CbG"), 5)),
        ("HET-03 2-hop metapath Compound-binds-Gene<-associates-hypertension",
         'MATCH (c:Compound)-[:CbG]->(g:Gene)<-[:DaG]-(d:Disease {name: "hypertension"}) '
         "RETURN DISTINCT c.name AS drug, g.name AS gene",
         lambda rows: ({(r["drug"], r["gene"]) for r in rows} == truth.drugs_binding_genes_of("hypertension")
                       and len(rows) == len(truth.drugs_binding_genes_of("hypertension")),
                       f"expected {len(truth.drugs_binding_genes_of('hypertension'))} distinct pairs")),
        ("HET-04 shared targets Doxorubicin & Methotrexate",
         'MATCH (a:Compound {name: "Doxorubicin"})-[:CbG]->(g:Gene)<-[:CbG]-(b:Compound {name: "Methotrexate"}) '
         "RETURN g.name AS gene ORDER BY gene",
         lambda rows: ([r["gene"] for r in rows] == truth.shared_targets("Doxorubicin", "Methotrexate"),
                       f"expected {truth.shared_targets('Doxorubicin', 'Methotrexate')}")),
        ("HET-05 top-5 diseases by associated genes",
         "MATCH (d:Disease)-[:DaG]->(g:Gene) RETURN d.name AS disease, count(g) AS n ORDER BY n DESC LIMIT 5",
         lambda rows: topk_ok(rows, "disease", "n", truth.count_by_source("DaG"), 5)),
    ]

    results: list[dict[str, Any]] = []
    for cid, cypher, check in checks:
        lat = []
        rows: list[dict] = []
        for _ in range(5):
            t = time.perf_counter()
            rows = run(cypher, graph)
            lat.append((time.perf_counter() - t) * 1000)
        ok, why = check(rows)
        lat.sort()
        results.append({"id": cid, "cypher": cypher, "rows": len(rows), "passed": bool(ok), "check": why,
                        "latency_ms_p50": round(lat[2], 2), "latency_ms_max": round(lat[-1], 2)})
        print(f"[{'PASS' if ok else 'FAIL'}] {cid}: {len(rows)} rows, p50 {lat[2]:.1f} ms" + ("" if ok else f"  ({why})"))

    # Datalog: CbG(c, g), DaG(d, g) => POTENTIALLY_TREATS(c, d). DaG points Disease -> Gene,
    # so the shared gene is the *object* of both atoms.
    rule = InferenceRule(
        name="cbg_dag_metapath",
        head=Atom("rel", ("?c", "POTENTIALLY_TREATS", "?d")),
        body=(Atom("rel", ("?c", "CbG", "?g")), Atom("rel", ("?d", "DaG", "?g"))),
        description="Compound binds a gene associated with a disease",
    )
    engine = InferenceEngine()
    engine.add_rule(rule)
    t = time.perf_counter()
    _, derived = engine.infer(graph)
    inf_s = time.perf_counter() - t
    got = {(f.args[0], f.args[2]) for f in derived if f.predicate == "rel" and f.args[1] == "POTENTIALLY_TREATS"}
    expected = truth.metapath_cbg_dag()
    inf_ok = got == expected and len(expected) > 0
    print(f"[{'PASS' if inf_ok else 'FAIL'}] Datalog CbG+DaG metapath: derived {len(got):,} facts, "
          f"independent join {len(expected):,}, {inf_s:.1f}s")

    passed = sum(r["passed"] for r in results) + int(inf_ok)
    total = len(results) + 1
    summary = {
        "evaluation": "GQL-Core vs independent Python ground truth on real Hetionet v1.0 (own evaluation, "
                      "not a published benchmark)",
        "dataset": {"source": "https://github.com/hetio/hetionet (v1.0)", "relations": dict(rel_counts),
                    "nodes": len(graph._nodes), "edges": len(edges)},
        "queries": results,
        "datalog": {"rule": "CbG(c,g) AND DaG(d,g) => POTENTIALLY_TREATS(c,d)", "derived": len(got),
                    "expected": len(expected), "passed": inf_ok, "seconds": round(inf_s, 2)},
        "passed": passed,
        "total": total,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"{passed}/{total} checks passed; saved {OUT}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
