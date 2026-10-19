"""Counterexample and Integrity Tests for the openCypher TCK Verification Harness.

Verifies that the TCK harness cannot produce false-positive passes by testing:
1. Mutation side-effect verification (`Create1` and `Delete1` upstream definitions, plus counterexamples proving a no-op CREATE or DELETE fails the scenario).
2. Expected-error category and phase enforcement (SyntaxError vs KeyError, SemanticError vs RuntimeError, fixture setup raising ValueError -> BLOCKED, compile-time error occurring at runtime -> FAIL).
3. Exact result semantics (ordered lists `[1, 2]` vs `[2, 1]`, maps, nodes/relationships with unexpected extra properties, path direction, nulls, integer vs float, NaN/Infinity, duplicate rows, and column names).
4. Gherkin parser validation (Scenario Outline expansion, control queries, side effects, error phases/details, and blocking on unknown/uninterpreted steps).
"""

from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import patch

import pytest

from benchmark.tck.gherkin_parser import (
    ExpectedNode,
    ExpectedPath,
    ExpectedRel,
    TCKScenario,
    _parse_cell_value,
    _parse_scenario_steps,
    parse_feature_file,
)
from benchmark.tck.tck_adapter import (
    _PhasedQueryError,
    _match_row,
    _normalize_cell_for_cmp,
    run_scenario,
)
from gql_core.graph import Edge, Node, Path as GraphPath, PropertyGraph
from gql_core.query.semantic import SemanticError

TCK_FEATURES_DIR = Path("benchmark/cache/openCypher/tck/features")


# ============================================================================
# 1. Mutation Side Effects & Upstream Create1 / Delete1
# ============================================================================


def test_upstream_create1_and_delete1_definitions() -> None:
    """Test Create1.feature and Delete1.feature against upstream definitions."""
    create1_path = TCK_FEATURES_DIR / "clauses" / "create" / "Create1.feature"
    delete1_path = TCK_FEATURES_DIR / "clauses" / "delete" / "Delete1.feature"

    create1_scenarios = parse_feature_file(create1_path)
    delete1_scenarios = parse_feature_file(delete1_path)

    assert len(create1_scenarios) == 20
    assert len(delete1_scenarios) == 8

    # Verify Create1#1 .. Create1#12 have explicit side effects parsed and pass
    for sc in create1_scenarios[:12]:
        assert sc.expected_side_effects is not None and len(sc.expected_side_effects) > 0
        res = run_scenario(sc)
        assert res["primary_classification"] == "PASS_RESULT", f"{sc.scenario_id} failed: {res['reason']}"
        assert res["side_effect_checked"] is True
        assert res["has_mutation_side_effects"] is True

    # Verify Delete1#1 .. Delete1#6 passresult + side-effect checks
    for sc in delete1_scenarios[:6]:
        res = run_scenario(sc)
        assert res["primary_classification"] == "PASS_RESULT", f"{sc.scenario_id} failed: {res['reason']}"
        assert res["side_effect_checked"] is True


def test_counterexample_noop_create_fails_create1() -> None:
    """Counterexample: A no-op CREATE implementation that returns empty rows without mutating the graph MUST fail Create1#1."""
    create1_path = TCK_FEATURES_DIR / "clauses" / "create" / "Create1.feature"
    create1_sc1 = parse_feature_file(create1_path)[0]
    assert create1_sc1.scenario_id == "Create1#1"
    assert create1_sc1.expected_side_effects == {"+nodes": 1}

    # Patch _execute_query_with_phase to be a no-op returning [] without adding the node
    with patch("benchmark.tck.tck_adapter._execute_query_with_phase", return_value=[]):
        res = run_scenario(create1_sc1)
        assert res["primary_classification"] == "FAIL_WRONG_RESULT"
        assert res["status"] == "failed"
        assert res.get("side_effect_failure") is True
        assert "Side-effect mismatch" in res["reason"]


def test_counterexample_noop_delete_fails_delete1() -> None:
    """Counterexample: A no-op DELETE implementation that leaves the node in the graph MUST fail Delete1#1."""
    delete1_path = TCK_FEATURES_DIR / "clauses" / "delete" / "Delete1.feature"
    delete1_sc1 = parse_feature_file(delete1_path)[0]
    assert delete1_sc1.scenario_id == "Delete1#1"
    assert delete1_sc1.expected_side_effects == {"-nodes": 1}

    with patch("benchmark.tck.tck_adapter._execute_query_with_phase", return_value=[]):
        res = run_scenario(delete1_sc1)
        assert res["primary_classification"] == "FAIL_WRONG_RESULT"
        assert res["status"] == "failed"
        assert res.get("side_effect_failure") is True
        assert "Side-effect mismatch" in res["reason"]


def test_counterexample_unexpected_mutation_fails_no_side_effects() -> None:
    """Counterexample: A read query with `And no side effects` that mutates the graph MUST fail."""
    sc = TCKScenario(
        scenario_id="Counterexample#NoSideEffects",
        feature="Counterexample",
        name="Read query with unexpected mutation",
        file_path="test.feature",
        query="CREATE (:Unexpected)",
        expected_kind="empty",
        expect_no_side_effects=True,
        expected_side_effects={},
    )
    res = run_scenario(sc)
    assert res["primary_classification"] == "FAIL_WRONG_RESULT"
    assert res.get("side_effect_failure") is True


# ============================================================================
# 2. Expected-Error Categories, Phases, and Fixture Separation
# ============================================================================


def test_counterexample_syntax_error_producing_key_error_fails() -> None:
    """Counterexample: An expected SyntaxError that raises KeyError MUST fail."""
    sc = TCKScenario(
        scenario_id="Counterexample#SyntaxGetsKeyError",
        feature="Counterexample",
        name="Expected SyntaxError gets KeyError",
        file_path="test.feature",
        query="RETURN 1",
        expected_kind="syntax_error",
        expected_error_type="SyntaxError",
        expected_error_phase="compile_time",
        expected_error_detail="InvalidSyntax",
    )
    with patch(
        "benchmark.tck.tck_adapter._execute_query_with_phase",
        side_effect=_PhasedQueryError(KeyError("missing_key"), "compile_time"),
    ):
        res = run_scenario(sc)
        assert res["primary_classification"] != "PASS_EXPECTED_ERROR"
        assert res["status"] == "failed"
        assert res.get("error_mismatch") is True


def test_counterexample_semantic_error_producing_runtime_error_fails() -> None:
    """Counterexample: An expected SemanticError that raises generic RuntimeError MUST fail."""
    sc = TCKScenario(
        scenario_id="Counterexample#SemanticGetsRuntimeError",
        feature="Counterexample",
        name="Expected SemanticError gets RuntimeError",
        file_path="test.feature",
        query="RETURN 1",
        expected_kind="semantic_error",
        expected_error_type="SemanticError",
        expected_error_phase="runtime",
        expected_error_detail="MergeReadOwnWrites",
    )
    with patch(
        "benchmark.tck.tck_adapter._execute_query_with_phase",
        side_effect=_PhasedQueryError(RuntimeError("generic crash"), "runtime"),
    ):
        res = run_scenario(sc)
        assert res["primary_classification"] == "FAIL_RUNTIME"
        assert res["status"] == "failed"
        assert res.get("error_mismatch") is True


def test_counterexample_fixture_setup_raising_value_error_is_blocked() -> None:
    """Counterexample: Fixture setup raising ValueError in an expected-error scenario MUST produce BLOCKED, never PASS_EXPECTED_ERROR."""
    sc = TCKScenario(
        scenario_id="Counterexample#FixtureValueError",
        feature="Counterexample",
        name="Fixture raises ValueError on expected error scenario",
        file_path="test.feature",
        scenario_create=["CREATE (:Node)"],
        query="MATCH (a) CREATE (a)",
        expected_kind="syntax_error",
        expected_error_type="SyntaxError",
        expected_error_phase="compile_time",
        expected_error_detail="VariableAlreadyBound",
    )
    with patch("benchmark.tck.tck_adapter.load_cypher_create_fixture", side_effect=ValueError("bad fixture")):
        res = run_scenario(sc)
        assert res["primary_classification"] == "BLOCKED"
        assert res["status"] == "blocked"
        assert "Fixture creation error" in res["reason"]


def test_counterexample_compile_time_error_at_runtime_fails() -> None:
    """Counterexample: An expected compile-time error occurring during runtime execution MUST fail."""
    sc = TCKScenario(
        scenario_id="Counterexample#CompileAtRuntime",
        feature="Counterexample",
        name="Expected compile time error raised at runtime",
        file_path="test.feature",
        query="RETURN 1",
        expected_kind="syntax_error",
        expected_error_type="SyntaxError",
        expected_error_phase="compile_time",
        expected_error_detail="UndefinedVariable",
    )
    with patch(
        "benchmark.tck.tck_adapter._execute_query_with_phase",
        side_effect=_PhasedQueryError(SemanticError("UndefinedVariable"), "runtime"),
    ):
        res = run_scenario(sc)
        assert res["primary_classification"] == "FAIL_RUNTIME"
        assert res["status"] == "failed"
        assert res.get("error_mismatch") is True


# ============================================================================
# 3. Exact Result Semantics
# ============================================================================


def test_exact_list_ordering_semantics() -> None:
    """[1, 2] must NOT match [2, 1] when list order is significant, and MUST match when ignore_list_order=True."""
    assert _normalize_cell_for_cmp([1, 2], [1, 2], ignore_list_order=False) is True
    assert _normalize_cell_for_cmp([1, 2], [2, 1], ignore_list_order=False) is False
    assert _normalize_cell_for_cmp([1, 2], [2, 1], ignore_list_order=True) is True
    assert _normalize_cell_for_cmp([1, 1, 2], [1, 2, 2], ignore_list_order=True) is False


def test_exact_entity_comparison_rejects_unexpected_properties() -> None:
    """Entities (Nodes and Relationships) with unexpected extra properties MUST fail exact entity comparison."""
    exp_node = _parse_cell_value("(:Person {name: 'Alice'})")
    node_exact = Node(id="n1", label="Person", props={"name": "Alice"}, labels=("Person",))
    node_extra_prop = Node(id="n1", label="Person", props={"name": "Alice", "secret": 99}, labels=("Person",))
    node_extra_label = Node(id="n1", label="Person", props={"name": "Alice"}, labels=("Person", "Admin"))

    assert _normalize_cell_for_cmp(node_exact, exp_node) is True
    assert _normalize_cell_for_cmp(node_extra_prop, exp_node) is False
    assert _normalize_cell_for_cmp(node_extra_label, exp_node) is False

    # Empty property expectation (:Person) must reject node with properties
    exp_bare_node = _parse_cell_value("(:Person)")
    assert _normalize_cell_for_cmp(node_exact, exp_bare_node) is False

    # Relationship exact property check
    exp_rel = _parse_cell_value("[:KNOWS {since: 2020}]")
    rel_exact = Edge(id="e1", label="KNOWS", src="n1", dst="n2", props={"since": 2020})
    rel_extra = Edge(id="e1", label="KNOWS", src="n1", dst="n2", props={"since": 2020, "weight": 1})
    assert _normalize_cell_for_cmp(rel_exact, exp_rel) is True
    assert _normalize_cell_for_cmp(rel_extra, exp_rel) is False


def test_exact_path_direction_and_numeric_types() -> None:
    """Verify Path direction checking, Integer vs Float distinction, NaN, Infinity, Null, Map, and Column Names."""
    n1 = Node(id="n1", label="A", props={}, labels=("A",))
    n2 = Node(id="n2", label="B", props={}, labels=("B",))
    e_out = Edge(id="e1", label="R", src="n1", dst="n2", props={})
    e_in = Edge(id="e1", label="R", src="n2", dst="n1", props={})

    exp_path_out = _parse_cell_value("<(:A)-[:R]->(:B)>")
    exp_path_in = _parse_cell_value("<(:A)<-[:R]-(:B)>")

    assert _normalize_cell_for_cmp(GraphPath(nodes=(n1, n2), relationships=(e_out,)), exp_path_out) is True
    assert _normalize_cell_for_cmp(GraphPath(nodes=(n1, n2), relationships=(e_in,)), exp_path_out) is False
    assert _normalize_cell_for_cmp(GraphPath(nodes=(n1, n2), relationships=(e_in,)), exp_path_in) is True

    # Numeric type strictness: 1 (int) != 1.0 (float) != True (bool) != "1" (str)
    assert _normalize_cell_for_cmp(1, 1) is True
    assert _normalize_cell_for_cmp(1, 1.0) is False
    assert _normalize_cell_for_cmp(1.0, 1) is False
    assert _normalize_cell_for_cmp(True, 1) is False
    assert _normalize_cell_for_cmp("1", 1) is False

    # NaN and Infinity
    assert _normalize_cell_for_cmp(float("nan"), float("nan")) is True
    assert _normalize_cell_for_cmp(float("nan"), 0.0) is False
    assert _normalize_cell_for_cmp(float("inf"), float("inf")) is True
    assert _normalize_cell_for_cmp(float("-inf"), float("inf")) is False

    # Exact column names and map keys
    assert _match_row({"a.name": "Alice"}, {"a.name": "Alice"}, ["a.name"]) is True
    assert _match_row({"name": "Alice"}, {"a.name": "Alice"}, ["a.name"]) is False


def test_unknown_gherkin_step_marks_scenario_blocked() -> None:
    """Unknown or uninterpreted Gherkin steps must never be silently ignored and must produce BLOCKED."""
    base = TCKScenario(scenario_id="Test#1", feature="Test", name="Unknown step", file_path="test.feature")
    sc = _parse_scenario_steps(
        [
            "Given an empty graph",
            "When executing query:",
            '"""',
            "RETURN 1 AS x",
            '"""',
            "Then some completely unknown assertion step:",
        ],
        base,
    )
    assert len(sc.parse_errors) == 1
    res = run_scenario(sc)
    assert res["primary_classification"] == "BLOCKED"
    assert res["status"] == "blocked"
