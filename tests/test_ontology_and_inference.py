"""Tests for Ontology Schema, Constraints, and Deterministic Inference in GQL-Core."""

from __future__ import annotations

import pytest

from gql_core import (
    CardinalityConstraint,
    Edge,
    EntityType,
    InferenceEngine,
    Node,
    OntologySchema,
    OntologyViolationError,
    PlanBuilder,
    PropertyDef,
    PropertyGraph,
    ReasoningMode,
    RelationshipType,
    eq,
    execute_plan,
    make_composition_rule,
    prop,
)


def test_ontology_subtype_hierarchy_and_validation():
    """Verify entity subtyping and constraint validation."""
    schema = OntologySchema()
    # Hierarchy: Animal -> Mammal -> Dog
    schema.add_entity(EntityType(name="Animal"))
    schema.add_entity(EntityType(name="Mammal", supertypes=("Animal",)))
    schema.add_entity(EntityType(name="Dog", supertypes=("Mammal",)))

    assert schema.is_subtype_of("Dog", "Dog") is True
    assert schema.is_subtype_of("Dog", "Mammal") is True
    assert schema.is_subtype_of("Dog", "Animal") is True
    assert schema.is_subtype_of("Animal", "Dog") is False

    # Relationship with irreflexive constraint and max cardinality
    schema.add_relationship(
        RelationshipType(
            name="PARENT_OF",
            source_type="Animal",
            target_type="Animal",
            is_irreflexive=True,
            cardinality=CardinalityConstraint(max_incoming=2),  # At most 2 parents
            inverse="CHILD_OF",
        )
    )

    g = PropertyGraph()
    g.add_node(Node(id="n1", label="Dog"))
    # Self-referential edge violates irreflexivity
    g.add_edge(Edge(id="e_self", label="PARENT_OF", src="n1", dst="n1"))

    violations = schema.validate_graph(g)
    assert any(v.code == "IRREFLEXIVE_VIOLATION" for v in violations)


def test_inference_inverse_symmetric_transitive_rules():
    """Verify Datalog-like inference engine derives inverse, symmetric, and transitive facts."""
    schema = OntologySchema()
    schema.add_relationship(
        RelationshipType(name="PARENT_OF", source_type="Node", target_type="Node", inverse="CHILD_OF")
    )
    schema.add_relationship(
        RelationshipType(name="SPOUSE_OF", source_type="Node", target_type="Node", is_symmetric=True)
    )
    schema.add_relationship(
        RelationshipType(name="LOCATED_IN", source_type="Node", target_type="Node", is_transitive=True)
    )

    g = PropertyGraph()
    # Family & Locations
    g.add_node(Node(id="john", label="Person"))
    g.add_node(Node(id="mary", label="Person"))
    g.add_node(Node(id="bob", label="Person"))
    g.add_node(Node(id="paris", label="City"))
    g.add_node(Node(id="france", label="Country"))
    g.add_node(Node(id="europe", label="Continent"))

    # Asserted facts
    g.add_edge(Edge(id="e1", label="PARENT_OF", src="john", dst="bob"))
    g.add_edge(Edge(id="e2", label="SPOUSE_OF", src="john", dst="mary"))
    g.add_edge(Edge(id="e3", label="LOCATED_IN", src="paris", dst="france"))
    g.add_edge(Edge(id="e4", label="LOCATED_IN", src="france", dst="europe"))

    engine = InferenceEngine(schema=schema)
    all_facts, new_facts = engine.infer(g)

    # 1. Inverse: bob CHILD_OF john
    child_facts = [f for f in new_facts if f.predicate == "rel" and f.args[1] == "CHILD_OF"]
    assert len(child_facts) == 1
    assert child_facts[0].args == ("bob", "CHILD_OF", "john")
    assert child_facts[0].rule_name == "inverse_PARENT_OF_CHILD_OF"

    # 2. Symmetric: mary SPOUSE_OF john
    spouse_facts = [f for f in new_facts if f.predicate == "rel" and f.args == ("mary", "SPOUSE_OF", "john")]
    assert len(spouse_facts) == 1
    assert spouse_facts[0].rule_name == "symmetric_SPOUSE_OF"

    # 3. Transitive: paris LOCATED_IN europe
    trans_facts = [f for f in new_facts if f.predicate == "rel" and f.args == ("paris", "LOCATED_IN", "europe")]
    assert len(trans_facts) == 1
    assert trans_facts[0].rule_name == "transitive_LOCATED_IN"


def test_custom_composition_rule_indirect_reports():
    """Verify user-defined recursive/composition rule:
    REPORTS_TO(A, B) AND REPORTS_TO(B, C) => INDIRECTLY_REPORTS_TO(A, C)
    """
    g = PropertyGraph()
    g.add_node(Node(id="eng", label="Employee", props={"name": "Engineer"}))
    g.add_node(Node(id="mgr", label="Employee", props={"name": "Manager"}))
    g.add_node(Node(id="dir", label="Employee", props={"name": "Director"}))

    g.add_edge(Edge(id="e1", label="REPORTS_TO", src="eng", dst="mgr"))
    g.add_edge(Edge(id="e2", label="REPORTS_TO", src="mgr", dst="dir"))

    engine = InferenceEngine()
    engine.add_rule(make_composition_rule("INDIRECTLY_REPORTS_TO", "REPORTS_TO", "REPORTS_TO"))

    # Materialize facts into a new graph
    inf_graph = engine.create_overlay_graph(g)

    # Query the derived relationship
    plan = (
        PlanBuilder.scan("a", "Employee")
        .expand("INDIRECTLY_REPORTS_TO", to_var="c", from_var="a")
        .project(
            (prop("a", "name"), "subordinate"),
            (prop("c", "name"), "executive"),
        )
        .build()
    )

    res = execute_plan(plan, inf_graph)
    assert len(res["rows"]) == 1
    assert res["rows"][0] == {"subordinate": "Engineer", "executive": "Director"}


def test_closed_world_vs_open_world_negation():
    """Verify CWA vs OWA reasoning declarations and negation behavior."""
    schema = OntologySchema()
    schema.add_relationship(
        RelationshipType(name="VERIFIED_BY", source_type="Node", target_type="Node", reasoning_mode=ReasoningMode.CWA)
    )
    schema.add_relationship(
        RelationshipType(name="SUSPECTED_OF", source_type="Node", target_type="Node", reasoning_mode=ReasoningMode.OWA)
    )

    assert schema.get_reasoning_mode("VERIFIED_BY") == ReasoningMode.CWA
    assert schema.get_reasoning_mode("SUSPECTED_OF") == ReasoningMode.OWA
