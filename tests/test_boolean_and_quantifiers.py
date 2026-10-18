"""Tests for Boolean predicate composition, graph existence, and quantified relationships in GQL-Core."""

from __future__ import annotations

import pytest

from gql_core import (
    Edge,
    Node,
    PlanBuilder,
    PropertyGraph,
    all_rel,
    and_,
    any_rel,
    at_least_rel,
    eq,
    execute_plan,
    exists,
    gt,
    is_null,
    lit,
    none_rel,
    not_,
    not_exists,
    or_,
    pattern,
    prop,
    quantified_rel,
    single_rel,
    var,
    col,
)
from gql_core.physical.evaluator import eval_predicate


@pytest.fixture
def org_graph() -> PropertyGraph:
    """Fixture graph containing employees, skills, departments, and statuses:
    - Alice: HAS_SKILL Python, HAS_SKILL Rust, WORKS_IN AI
    - Bob: HAS_SKILL Python, HAS_STATUS Left
    - Charlie: HAS_SKILL Java, WORKS_IN Finance
    - Dana: No skills, WORKS_IN AI
    """
    g = PropertyGraph()
    # Nodes
    g.add_node(Node(id="alice", label="Employee", props={"name": "Alice", "status": "active"}))
    g.add_node(Node(id="bob", label="Employee", props={"name": "Bob", "status": "former"}))
    g.add_node(Node(id="charlie", label="Employee", props={"name": "Charlie", "status": "active"}))
    g.add_node(Node(id="dana", label="Employee", props={"name": "Dana", "status": "active"}))

    g.add_node(Node(id="python", label="Skill", props={"name": "Python"}))
    g.add_node(Node(id="rust", label="Skill", props={"name": "Rust"}))
    g.add_node(Node(id="java", label="Skill", props={"name": "Java"}))

    g.add_node(Node(id="ai", label="Dept", props={"name": "AI"}))
    g.add_node(Node(id="finance", label="Dept", props={"name": "Finance"}))

    g.add_node(Node(id="left_status", label="Status", props={"name": "Left"}))

    # Edges
    g.add_edge(Edge(id="e1", label="HAS_SKILL", src="alice", dst="python"))
    g.add_edge(Edge(id="e2", label="HAS_SKILL", src="alice", dst="rust"))
    g.add_edge(Edge(id="e3", label="WORKS_IN", src="alice", dst="ai"))

    g.add_edge(Edge(id="e4", label="HAS_SKILL", src="bob", dst="python"))
    g.add_edge(Edge(id="e5", label="HAS_STATUS", src="bob", dst="left_status"))

    g.add_edge(Edge(id="e6", label="HAS_SKILL", src="charlie", dst="java"))
    g.add_edge(Edge(id="e7", label="WORKS_IN", src="charlie", dst="finance"))

    g.add_edge(Edge(id="e8", label="WORKS_IN", src="dana", dst="ai"))

    return g


def test_three_valued_logic_truth_tables():
    """Verify Kleene 3VL truth tables for AND, OR, NOT."""
    # NOT
    assert eval_predicate(not_(lit(True)), {}) is False
    assert eval_predicate(not_(lit(False)), {}) is True
    assert eval_predicate(not_(is_null(lit(1))), {}) is True  # NOT False -> True
    # Comparison against None yields None (Unknown)
    null_comp = eq(lit(None), lit(2))
    assert eval_predicate(null_comp, {}) is None
    assert eval_predicate(not_(null_comp), {}) is None  # NOT Unknown -> Unknown

    # AND
    # False AND Unknown -> False (short-circuit)
    assert eval_predicate(and_(lit(False), null_comp), {}) is False
    # True AND Unknown -> Unknown
    assert eval_predicate(and_(lit(True), null_comp), {}) is None
    # True AND True -> True
    assert eval_predicate(and_(lit(True), lit(True)), {}) is True

    # OR
    # True OR Unknown -> True (short-circuit)
    assert eval_predicate(or_(lit(True), null_comp), {}) is True
    # False OR Unknown -> Unknown
    assert eval_predicate(or_(lit(False), null_comp), {}) is None
    # False OR False -> False
    assert eval_predicate(or_(lit(False), lit(False)), {}) is False


def test_and_exists_and_not_exists(org_graph: PropertyGraph):
    """Test: AND(EXISTS(HAS_SKILL Python), NOT_EXISTS(HAS_STATUS Left)).

    Alice has Python and not Left -> MATCH
    Bob has Python but has Left -> EXCLUDED
    Charlie has Java -> EXCLUDED
    """
    has_python = pattern("e", "HAS_SKILL", "s", target_filter=eq(prop("s", "name"), lit("Python")))
    has_left = pattern("e", "HAS_STATUS", "st", target_filter=eq(prop("st", "name"), lit("Left")))

    plan = (
        PlanBuilder.scan("e", "Employee")
        .filter(and_(exists(has_python), not_exists(has_left)))
        .project((prop("e", "name"), "name"))
        .build()
    )

    res = execute_plan(plan, org_graph)
    assert res["count"] == 1
    assert res["rows"] == [{"name": "Alice"}]


def test_nested_boolean_composition_graph_predicates(org_graph: PropertyGraph):
    """Test the mission specification example:
    AND(
      EXISTS(person -[HAS_SKILL]-> Python),
      OR(
        EXISTS(person -[WORKS_IN]-> AI),
        EXISTS(person -[HAS_SKILL]-> Rust)
      ),
      NOT_EXISTS(person -[HAS_STATUS]-> Left)
    )
    """
    has_python = pattern("p", "HAS_SKILL", "s1", target_filter=eq(prop("s1", "name"), lit("Python")))
    works_in_ai = pattern("p", "WORKS_IN", "d", target_filter=eq(prop("d", "name"), lit("AI")))
    has_rust = pattern("p", "HAS_SKILL", "s2", target_filter=eq(prop("s2", "name"), lit("Rust")))
    has_left = pattern("p", "HAS_STATUS", "st", target_filter=eq(prop("st", "name"), lit("Left")))

    condition = and_(
        exists(has_python),
        or_(exists(works_in_ai), exists(has_rust)),
        not_exists(has_left),
    )

    plan = (
        PlanBuilder.scan("p", "Employee")
        .filter(condition)
        .project((prop("p", "name"), "name"))
        .build()
    )

    res = execute_plan(plan, org_graph)
    assert res["count"] == 1
    assert res["rows"] == [{"name": "Alice"}]


def test_quantified_relationship_reasoning(org_graph: PropertyGraph):
    """Test AT_LEAST, ALL with vacuous truth, NONE, and SINGLE."""
    # 1. AT_LEAST(2, HAS_SKILL) -> Only Alice has 2 skills (Python, Rust)
    plan_at_least = (
        PlanBuilder.scan("e", "Employee")
        .filter(at_least_rel(2, "e", "HAS_SKILL", "s"))
        .project((prop("e", "name"), "name"))
        .build()
    )
    res_at_least = execute_plan(plan_at_least, org_graph)
    assert res_at_least["rows"] == [{"name": "Alice"}]

    # 2. ALL: employees whose skills all start with 'P'
    # Bob only has 'Python' -> ALL matches True
    # Alice has 'Python' and 'Rust' -> ALL matches False
    # Dana has 0 skills -> ALL is vacuously True!
    from gql_core import starts_with

    skill_starts_with_p = starts_with(prop("s", "name"), lit("P"))
    plan_all = (
        PlanBuilder.scan("e", "Employee")
        .filter(all_rel("e", "HAS_SKILL", "s", predicate=skill_starts_with_p))
        .project((prop("e", "name"), "name"))
        .sort((col("name"), "ASC"))
        .build()
    )
    res_all = execute_plan(plan_all, org_graph)
    names = [r["name"] for r in res_all["rows"]]
    assert "Bob" in names
    assert "Dana" in names  # Vacuous truth!
    assert "Alice" not in names

    # 3. NONE: employees with NONE of their skills starting with 'P'
    # Charlie has Java -> True
    # Dana has 0 skills -> True
    plan_none = (
        PlanBuilder.scan("e", "Employee")
        .filter(none_rel("e", "HAS_SKILL", "s", predicate=skill_starts_with_p))
        .project((prop("e", "name"), "name"))
        .build()
    )
    res_none = execute_plan(plan_none, org_graph)
    none_names = {r["name"] for r in res_none["rows"]}
    assert "Charlie" in none_names
    assert "Dana" in none_names
    assert "Alice" not in none_names

    # 4. SINGLE: employees with exactly 1 skill
    # Bob (Python) and Charlie (Java) each have 1 skill
    plan_single = (
        PlanBuilder.scan("e", "Employee")
        .filter(single_rel("e", "HAS_SKILL", "s"))
        .project((prop("e", "name"), "name"))
        .build()
    )
    res_single = execute_plan(plan_single, org_graph)
    single_names = {r["name"] for r in res_single["rows"]}
    assert single_names == {"Bob", "Charlie"}


def test_correlated_subquery_in_exists(org_graph: PropertyGraph):
    """Test EXISTS with a correlated subquery plan checking skills."""
    # Subquery: scan skill s, filter s.name = 'Rust' and join with e on HAS_SKILL
    sub_plan = (
        PlanBuilder.scan("s", "Skill", name="Rust")
        .build()
    )

    # Use pattern-based exists with filter
    pat = pattern("e", "HAS_SKILL", "s", target_filter=eq(prop("s", "name"), lit("Rust")))
    plan = (
        PlanBuilder.scan("e", "Employee")
        .filter(exists(pat))
        .project((prop("e", "name"), "name"))
        .build()
    )
    res = execute_plan(plan, org_graph)
    assert res["rows"] == [{"name": "Alice"}]
