"""
Domain Demonstration 1: Legal Knowledge Graph & Precedent Reasoning.

This demonstrates how GQL-Core is used to model legal statutes, court hierarchies,
precedent citations, and derive overturned precedents using Datalog-style ontology rules.

Use Case:
- Jurisdictions & Courts: US Supreme Court binds Circuit Courts; Circuit Courts bind District Courts.
- Case Law: Landmark cases cite earlier decisions.
- Precedent Invalidation: When a higher court overrules a decision, any lower court decision
  strictly relying on that precedent becomes questioned/overruled through transitive reasoning.
"""

from gql_core import PropertyGraph, Node, Edge, run
from gql_core.inference import (
    InferenceEngine,
    make_transitive_rule,
    make_composition_rule,
)


def run_legal_demonstration():
    print("=" * 70)
    print(" GQL-Core Domain Demo 1: Legal Knowledge Graph & Precedent Reasoning")
    print("=" * 70)

    # 1. Initialize property graph
    graph = PropertyGraph()

    # 2. Add Courts
    graph.add_node(Node("scotus", "Court", {"name": "Supreme Court of the United States", "tier": 1}))
    graph.add_node(Node("ca9", "Court", {"name": "9th Circuit Court of Appeals", "tier": 2}))
    graph.add_node(Node("d_cal", "Court", {"name": "U.S. District Court, N.D. Cal", "tier": 3}))

    # Jurisdictional hierarchy: scotus BINDS ca9, ca9 BINDS d_cal
    graph.add_edge(Edge("b1", "BINDS", "scotus", "ca9"))
    graph.add_edge(Edge("b2", "BINDS", "ca9", "d_cal"))

    # 3. Add Precedent Cases
    graph.add_node(Node("case_old", "Case", {"title": "OldPrecedent v. State", "year": 1980}))
    graph.add_node(Node("case_dist", "Case", {"title": "LocalApp v. TechCorp", "year": 2015}))
    graph.add_node(Node("case_new", "Case", {"title": "ModernStandard v. FederalAgency", "year": 2024}))

    # Decided In
    graph.add_edge(Edge("d1", "DECIDED_IN", "case_old", "ca9"))
    graph.add_edge(Edge("d2", "DECIDED_IN", "case_dist", "d_cal"))
    graph.add_edge(Edge("d3", "DECIDED_IN", "case_new", "scotus"))

    # Relationships: LocalApp RELIES_ON OldPrecedent; OldPrecedent OVERRULED_BY ModernStandard
    graph.add_edge(Edge("r1", "RELIES_ON", "case_dist", "case_old"))
    graph.add_edge(Edge("r2", "OVERRULED_BY", "case_old", "case_new"))

    print("\n[Step 1] Executing Cypher query on raw case citations...")
    raw_query = """
        MATCH (c1:Case)-[r:RELIES_ON]->(c2:Case)
        RETURN c1.title AS citing_case, c2.title AS cited_precedent
    """
    citations = run(raw_query, graph)
    for c in citations:
        print(f"  * '{c['citing_case']}' relies upon precedent: '{c['cited_precedent']}'")

    # 4. Set up Formal Legal Inference
    # Rule A: Jurisdictional binding is transitive (SCOTUS binds CA9, CA9 binds D_Cal -> SCOTUS binds D_Cal)
    # Rule B: Composition: If ?a RELIES_ON ?b and ?b OVERRULED_BY ?c -> ?a RESTS_ON_OVERRULED_LAW ?c
    engine = InferenceEngine()
    engine.add_rule(make_transitive_rule("BINDS"))
    engine.add_rule(
        make_composition_rule("RESTS_ON_OVERRULED_LAW", "RELIES_ON", "OVERRULED_BY")
    )

    print("\n[Step 2] Applying Legal Reasoning Rules via GQL-Core Inference Engine...")
    facts_by_rel, derived_facts = engine.infer(graph)

    # Inspect derived facts with provenance
    derived_foundations = [
        f for f in derived_facts if f.predicate == "rel" and f.args[1] == "RESTS_ON_OVERRULED_LAW"
    ]
    for fact in derived_foundations:
        src, rel, dst = fact.args
        print(f"  [DERIVED INFERENCE] Case '{src}' is flagged as '{rel}' (Due to: '{dst}')")
        print(f"  [PROVENANCE RULE]   Derived by rule: '{fact.rule_name}'")

    # 5. Materialize back into the PropertyGraph & Query
    engine.materialize(graph)

    print("\n[Step 3] Querying the materialized graph for compromised cases...")
    compromised_query = """
        MATCH (c:Case)-[:RESTS_ON_OVERRULED_LAW]->(bad:Case)
        RETURN c.title AS affected_case, bad.title AS overruling_precedent
    """
    for res in run(compromised_query, graph):
        print(f"  * ALERT: Case '{res['affected_case']}' rests on law overruled by '{res['overruling_precedent']}'!")

    print("\nDemonstration 1 (Legal KG) executed successfully.\n")


if __name__ == "__main__":
    run_legal_demonstration()
