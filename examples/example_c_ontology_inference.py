"""Example C — Ontology Inference & Datalog Rule Reasoning.

Demonstrates:
- Defining declarative inference rules (Transitive, Inverse, and Composition rules).
- Asserting explicit ground facts in an in-memory PropertyGraph.
- Running the stratified Datalog inference engine (InferenceEngine).
- Inspecting derived relationship facts and their rule provenance.
- Materializing derived relationships back into the graph for Cypher querying.

Run with:
    python examples/example_c_ontology_inference.py
"""

from __future__ import annotations

import gql_core
from gql_core import Edge, Node, PropertyGraph
from gql_core.inference import (
    InferenceEngine,
    make_composition_rule,
    make_inverse_rule,
    make_transitive_rule,
)


def main() -> None:
    # 1. Initialize Graph and assert base facts (Organizational & Infrastructure Hierarchy)
    graph = PropertyGraph()

    # Nodes: Org Units & Teams
    graph.add_node(Node(id="corp", label="OrgUnit", props={"name": "AcmeCorp"}))
    graph.add_node(Node(id="eng_div", label="OrgUnit", props={"name": "EngineeringDivision"}))
    graph.add_node(Node(id="core_team", label="Team", props={"name": "CorePlatformTeam"}))
    graph.add_node(Node(id="data_team", label="Team", props={"name": "DataInfraTeam"}))

    # Asserted direct relationships: PART_OF hierarchy
    # core_team -> eng_div -> corp
    graph.add_edge(Edge(id="e1", label="PART_OF", src="core_team", dst="eng_div"))
    graph.add_edge(Edge(id="e2", label="PART_OF", src="data_team", dst="eng_div"))
    graph.add_edge(Edge(id="e3", label="PART_OF", src="eng_div", dst="corp"))

    # Asserted management relationship:
    graph.add_node(Node(id="lead_alice", label="Person", props={"name": "Alice"}))
    graph.add_edge(Edge(id="e4", label="MANAGES", src="lead_alice", dst="core_team"))

    print(f"Asserted graph: {len(graph._nodes)} nodes, {len(graph._edges)} direct edges.")

    # 2. Define Ontology Inference Rules
    # Rule 1: Transitive PART_OF (if A PART_OF B and B PART_OF C => A PART_OF C)
    transitive_part_of = make_transitive_rule("PART_OF")

    # Rule 2: Inverse relationship (if A MANAGES B => B MANAGED_BY A)
    inverse_manages = make_inverse_rule("MANAGES", "MANAGED_BY")

    # Rule 3: Composition (if X MANAGES Y and Y PART_OF Z => X LEADS_IN Z)
    leads_in_org = make_composition_rule("LEADS_IN", "MANAGES", "PART_OF")

    # 3. Configure the Inference Engine
    engine = InferenceEngine()
    engine.add_rule(transitive_part_of)
    engine.add_rule(inverse_manages)
    engine.add_rule(leads_in_org)

    # 4. Run Datalog Fixed-Point Inference
    facts_by_rel, derived_facts = engine.infer(graph)

    print(f"\nInference complete: {len(derived_facts)} new facts derived at fixed point.")

    # 5. Inspect Derived Facts and their Provenance
    print("\n--- Derived Relationships with Rule Provenance ---")
    for fact in derived_facts:
        if fact.predicate == "rel":
            src, rel, dst = fact.args
            provenance = fact.rule_name or "inferred"
            print(f"  [Derived] ({src}) -[:{rel}]-> ({dst})  [Rule: {provenance}]")

    # Verify expected deductions:
    # core_team PART_OF corp (transitive)
    # data_team PART_OF corp (transitive)
    # core_team MANAGED_BY lead_alice (inverse)
    # lead_alice LEADS_IN eng_div (composition: MANAGES + PART_OF)
    derived_signatures = {(f.args[1], (f.args[0], f.args[2])) for f in derived_facts if f.predicate == "rel"}
    assert ("PART_OF", ("core_team", "corp")) in derived_signatures
    assert ("PART_OF", ("data_team", "corp")) in derived_signatures
    assert ("MANAGED_BY", ("core_team", "lead_alice")) in derived_signatures
    assert ("LEADS_IN", ("lead_alice", "eng_div")) in derived_signatures

    # 6. Materialize Inferred Relationships back into the PropertyGraph
    added_count = engine.materialize(graph)
    print(f"\nMaterialized {added_count} inferred edges into graph. Total edges: {len(graph._edges)}")

    # 7. Query Derived Knowledge seamlessly via openCypher / GQL
    query = """
    MATCH (p:Person)-[:LEADS_IN]->(unit:OrgUnit)
    RETURN p.name AS leader, unit.name AS division
    ORDER BY division ASC
    """
    rows = gql_core.run(query, graph)
    print("\n--- Query over Materialized Inferred Knowledge ---")
    for r in rows:
        print(f"  Leader: {r['leader']} leads {r['division']}")

    assert rows == [
        {"leader": "Alice", "division": "AcmeCorp"},
        {"leader": "Alice", "division": "EngineeringDivision"},
    ]

    print("\nExample C completed successfully.")


if __name__ == "__main__":
    main()
