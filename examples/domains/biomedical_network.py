"""
Domain Demonstration 3: Biomedical Knowledge Graph & Drug Interaction Inference.

This demonstrates how GQL-Core is used to model biomedical entities:
Diseases, Target Proteins, and Pharmaceutical Drugs, inferring contraindications
based on biological mechanism overlap.

Use Case:
- Drugs target Proteins (TARGETS).
- Fluconazole INHIBITS CYP2C9; CYP2C9 METABOLIZES Warfarin.
- Composition rule: If Drug A INHIBITS Enzyme E and Enzyme E METABOLIZES Drug B -> Drug A CONTRAINDICATED_WITH Drug B.
"""

from gql_core import PropertyGraph, Node, Edge, run
from gql_core.inference import (
    InferenceEngine,
    make_composition_rule,
)


def run_biomedical_demonstration():
    print("=" * 70)
    print(" GQL-Core Domain Demo 3: Biomedical Knowledge Graph & Drug Reasoning")
    print("=" * 70)

    # 1. Initialize property graph
    graph = PropertyGraph()

    # 2. Add Entities
    # Drugs
    graph.add_node(Node("drug_warfarin", "Drug", {"name": "Warfarin", "type": "anticoagulant"}))
    graph.add_node(Node("drug_fluconazole", "Drug", {"name": "Fluconazole", "type": "antifungal"}))
    graph.add_node(Node("drug_aspirin", "Drug", {"name": "Aspirin", "type": "nsaid"}))

    # Proteins / Enzymes
    graph.add_node(Node("protein_cyp2c9", "Protein", {"name": "CYP2C9", "function": "metabolism"}))
    graph.add_node(Node("protein_cox1", "Protein", {"name": "COX-1", "function": "platelet_aggregation"}))

    # Diseases / Indications
    graph.add_node(Node("disease_thrombosis", "Disease", {"name": "Deep Vein Thrombosis"}))

    # Edges
    # Fluconazole INHIBITS CYP2C9; CYP2C9 METABOLIZES Warfarin
    graph.add_edge(Edge("m1", "INHIBITS", "drug_fluconazole", "protein_cyp2c9"))
    graph.add_edge(Edge("m2", "METABOLIZES", "protein_cyp2c9", "drug_warfarin"))

    # Aspirin inhibits COX-1
    graph.add_edge(Edge("m3", "INHIBITS", "drug_aspirin", "protein_cox1"))

    # Warfarin treats thrombosis
    graph.add_edge(Edge("t1", "TREATS", "drug_warfarin", "disease_thrombosis"))

    print("\n[Step 1] Querying drug targets and metabolic mechanisms via Cypher...")
    mech_query = """
        MATCH (d:Drug)-[r]->(p:Protein)
        RETURN d.name AS drug, type(r) AS interaction, p.name AS protein
        ORDER BY drug ASC
    """
    for row in run(mech_query, graph):
        print(f"  * Drug {row['drug']} -[{row['interaction']}]-> Protein {row['protein']}")

    # 3. Setup Ontological Rule for Adverse Drug Interactions
    # If Drug A INHIBITS Enzyme E, and Enzyme E METABOLIZES Drug B -> Drug A CONTRAINDICATED_WITH Drug B
    engine = InferenceEngine()
    engine.add_rule(
        make_composition_rule("CONTRAINDICATED_WITH", "INHIBITS", "METABOLIZES")
    )

    print("\n[Step 2] Executing Biological Pathway Contraindication Inference...")
    facts_by_rel, derived_facts = engine.infer(graph)

    # Inspect derived facts
    for f in derived_facts:
        if f.predicate == "rel" and f.args[1] == "CONTRAINDICATED_WITH":
            src, rel, dst = f.args
            print(f"  [BIO INFERENCE] '{src}' is derived '{rel}' '{dst}'")
            print(f"  [MECHANISM RULE] Derived by rule: '{f.rule_name}'")

    # 4. Materialize and Query
    engine.materialize(graph)

    print("\n[Step 3] Querying clinical safety alert for patients on Warfarin...")
    safety_query = """
        MATCH (suspect:Drug)-[:CONTRAINDICATED_WITH]->(base:Drug {name: 'Warfarin'})
        RETURN suspect.name AS dangerous_drug, suspect.type AS drug_class, base.name AS prescribed_drug
    """
    for alert in run(safety_query, graph):
        print(f"  * CLINICAL ALERT: Do NOT co-prescribe {alert['dangerous_drug']} ({alert['drug_class']}) with {alert['prescribed_drug']}!")

    print("\nDemonstration 3 (Biomedical KG) executed successfully.\n")


if __name__ == "__main__":
    run_biomedical_demonstration()
