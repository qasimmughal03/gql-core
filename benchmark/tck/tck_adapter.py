"""openCypher TCK Scenario Execution Adapter for GQL-Core.

Executes TCK scenarios strictly through GQL-Core's public query API and verifies:
1. Exact result rows, values, types (ordered lists, maps, nodes, relationships, paths, nulls, NaN/Inf), multiplicities, ordering, and column names.
2. Mutation side effects (`+nodes`, `-nodes`, `+relationships`, `-relationships`, `+labels`, `-labels`, `+properties`, `-properties`, and `no side effects`) before any control query.
3. Optional control query execution and exact result assertions.
4. Expected error categories and compile-time vs. runtime phases, strictly separated from fixture setup.
"""

from __future__ import annotations

import copy
import math
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lark.exceptions import LarkError

from gql_core import PropertyGraph, run as run_query
from gql_core.query.executor import _is_pipeline_query, execute, execute_pipeline, plan_query
from gql_core.query.parser import parse
from gql_core.query.semantic import SemanticError, validate_query
from gql_core.temporal import Date, DateTime, Duration, Time
from gql_core.types import TypeErrorDiagnostic
from benchmark.tck.classifier import classify_query
from benchmark.tck.fixture_loader import load_cypher_create_fixture
from benchmark.tck.gherkin_parser import (
    ExpectedNode,
    ExpectedPath,
    ExpectedRel,
    TCKScenario,
    _parse_cell_value,
)

_NAMED_GRAPHS_DIR = Path(__file__).resolve().parent.parent / "cache" / "openCypher" / "tck" / "graphs"


class EntityNotFoundError(Exception):
    """Explicit exception class for openCypher EntityNotFound runtime errors."""


class ConstraintVerificationError(Exception):
    """Explicit exception class for openCypher ConstraintVerificationFailed runtime errors."""


class ProcedureError(Exception):
    """Explicit exception class for openCypher ProcedureError compile/runtime errors."""


class ParameterMissingError(Exception):
    """Explicit exception class for openCypher ParameterMissing compile/runtime errors."""


class ArgumentError(ValueError):
    """Explicit exception class for openCypher ArgumentError runtime errors."""


@dataclass
class GraphSnapshot:
    node_ids: frozenset[str]
    edge_ids: frozenset[str]
    graph_labels: frozenset[str]
    node_props: dict[str, dict[str, Any]]
    edge_props: dict[str, dict[str, Any]]


def _snapshot_graph(graph: PropertyGraph) -> GraphSnapshot:
    """Capture graph state (nodes, relationships, graph-wide active labels, and properties)."""
    node_ids = frozenset(graph._nodes.keys())
    edge_ids = frozenset(eid for eid in graph._edges.keys() if not eid.endswith("_rev"))
    labels: set[str] = set()
    node_props: dict[str, dict[str, Any]] = {}
    for nid, n in graph._nodes.items():
        n_lbls = getattr(n, "labels", ()) or ((n.label,) if getattr(n, "label", None) and n.label != "Node" else ())
        for lbl in n_lbls:
            if lbl and lbl != "Node":
                labels.add(lbl)
        node_props[nid] = {k: copy.deepcopy(v) for k, v in n.props.items() if v is not None}

    edge_props: dict[str, dict[str, Any]] = {}
    for eid, e in graph._edges.items():
        if eid.endswith("_rev"):
            continue
        edge_props[eid] = {k: copy.deepcopy(v) for k, v in e.props.items() if v is not None}

    return GraphSnapshot(
        node_ids=node_ids,
        edge_ids=edge_ids,
        graph_labels=frozenset(labels),
        node_props=node_props,
        edge_props=edge_props,
    )


def _props_equal(a: Any, b: Any) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, float) and math.isnan(a):
        return math.isnan(b)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(_props_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return set(a.keys()) == set(b.keys()) and all(_props_equal(a[k], b[k]) for k in a)
    return a == b


def _compute_side_effects(before: GraphSnapshot, after: GraphSnapshot) -> dict[str, int]:
    """Compute openCypher TCK side-effect deltas between two graph snapshots."""
    se: dict[str, int] = {}
    plus_nodes = len(after.node_ids - before.node_ids)
    minus_nodes = len(before.node_ids - after.node_ids)
    plus_rels = len(after.edge_ids - before.edge_ids)
    minus_rels = len(before.edge_ids - after.edge_ids)
    plus_labels = len(after.graph_labels - before.graph_labels)
    minus_labels = len(before.graph_labels - after.graph_labels)

    plus_props = 0
    minus_props = 0

    for nid in after.node_ids - before.node_ids:
        plus_props += len(after.node_props.get(nid, {}))
    for nid in before.node_ids - after.node_ids:
        minus_props += len(before.node_props.get(nid, {}))
    for nid in before.node_ids & after.node_ids:
        b_p = before.node_props.get(nid, {})
        a_p = after.node_props.get(nid, {})
        for k in b_p.keys() | a_p.keys():
            if k not in b_p and k in a_p:
                plus_props += 1
            elif k in b_p and k not in a_p:
                minus_props += 1
            elif not _props_equal(b_p[k], a_p[k]):
                plus_props += 1
                minus_props += 1

    for eid in after.edge_ids - before.edge_ids:
        plus_props += len(after.edge_props.get(eid, {}))
    for eid in before.edge_ids - after.edge_ids:
        minus_props += len(before.edge_props.get(eid, {}))
    for eid in before.edge_ids & after.edge_ids:
        b_p = before.edge_props.get(eid, {})
        a_p = after.edge_props.get(eid, {})
        for k in b_p.keys() | a_p.keys():
            if k not in b_p and k in a_p:
                plus_props += 1
            elif k in b_p and k not in a_p:
                minus_props += 1
            elif not _props_equal(b_p[k], a_p[k]):
                plus_props += 1
                minus_props += 1

    if plus_nodes:
        se["+nodes"] = plus_nodes
    if minus_nodes:
        se["-nodes"] = minus_nodes
    if plus_rels:
        se["+relationships"] = plus_rels
    if minus_rels:
        se["-relationships"] = minus_rels
    if plus_labels:
        se["+labels"] = plus_labels
    if minus_labels:
        se["-labels"] = minus_labels
    if plus_props:
        se["+properties"] = plus_props
    if minus_props:
        se["-properties"] = minus_props
    return se


def _load_named_graph(graph_name: str, graph: PropertyGraph) -> None:
    """Load pre-defined named graph fixtures (e.g. binary-tree-1, binary-tree-2)."""
    cypher_file = _NAMED_GRAPHS_DIR / graph_name / f"{graph_name}.cypher"
    if not cypher_file.exists():
        raise FileNotFoundError(f"Named graph fixture not found: {cypher_file}")
    content = cypher_file.read_text(encoding="utf-8")
    load_cypher_create_fixture(content, graph)


def _normalize_cell_for_cmp(actual: Any, expected: Any, ignore_list_order: bool = False) -> bool:
    """Strictly compare an actual GQL-Core binding value with an expected TCK value.

    Enforces exact openCypher value and type semantics:
    - Ordered lists by default (unordered only when ignore_list_order=True)
    - Exact map key/value sets
    - Exact node label sets and exact property maps (extra properties fail)
    - Exact relationship types and exact property maps (extra properties fail)
    - Exact path node sequence, relationship sequence, and traversal directions
    - Exact null, boolean, integer vs. float, NaN, and +/-Infinity semantics
    - Exact string equality without diagnostic normalization
    """
    # If caller passed raw Gherkin string for node/rel/path in unit tests, parse it first
    if isinstance(expected, str):
        s_exp = expected.strip()
        if s_exp.startswith("<") and s_exp.endswith(">") and "(" in s_exp and ")" in s_exp:
            expected = _parse_cell_value(s_exp)
        elif s_exp.startswith("(") and s_exp.endswith(")") and hasattr(actual, "label") and hasattr(actual, "props"):
            expected = _parse_cell_value(s_exp)
        elif (s_exp.startswith("[:") or s_exp.startswith("-[:") or s_exp.startswith("<-[:")) and hasattr(actual, "src") and hasattr(actual, "dst"):
            clean_rel = s_exp.lstrip("<-").rstrip("->").strip()
            expected = _parse_cell_value(clean_rel)

    # 1. Null comparison
    if expected is None:
        return actual is None
    if actual is None:
        return False

    # 2. NaN comparison
    if isinstance(expected, float) and math.isnan(expected):
        return isinstance(actual, float) and not isinstance(actual, bool) and math.isnan(actual)
    if isinstance(actual, float) and not isinstance(actual, bool) and math.isnan(actual):
        return False

    # 3. Boolean comparison
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual is expected
    if isinstance(actual, bool):
        return False

    # 4. Integer comparison (must be int, never float or bool)
    if isinstance(expected, int):
        return isinstance(actual, int) and actual == expected

    # 5. Float comparison (must be float, never int or bool)
    if isinstance(expected, float):
        if not isinstance(actual, float):
            return False
        if math.isinf(expected):
            return math.isinf(actual) and (expected > 0) == (actual > 0)
        if math.isinf(actual):
            return False
        return math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9)

    # 6. Node entity comparison (exact label set + exact property map)
    if isinstance(expected, ExpectedNode):
        if not (hasattr(actual, "label") and hasattr(actual, "props") and not hasattr(actual, "src")):
            return False
        actual_labels = frozenset(
            lbl
            for lbl in (getattr(actual, "labels", ()) or ((actual.label,) if actual.label and actual.label != "Node" else ()))
            if lbl and lbl != "Node"
        )
        if actual_labels != expected.labels:
            return False
        actual_props = {k: v for k, v in actual.props.items() if v is not None}
        return _compare_maps_strict(actual_props, expected.props, ignore_list_order=ignore_list_order)

    # 7. Relationship entity comparison (exact type + exact property map)
    if isinstance(expected, ExpectedRel):
        if not (hasattr(actual, "src") and hasattr(actual, "dst") and hasattr(actual, "props")):
            return False
        if expected.rel_type and actual.label != expected.rel_type:
            return False
        actual_props = {k: v for k, v in actual.props.items() if v is not None}
        return _compare_maps_strict(actual_props, expected.props, ignore_list_order=ignore_list_order)

    # 8. Path value comparison (exact nodes, relationships, and step directions)
    if isinstance(expected, ExpectedPath):
        if not (hasattr(actual, "nodes") and hasattr(actual, "relationships")):
            return False
        if len(actual.nodes) != len(expected.nodes) or len(actual.relationships) != len(expected.rels):
            return False
        for an, en in zip(actual.nodes, expected.nodes):
            if not _normalize_cell_for_cmp(an, en, ignore_list_order=ignore_list_order):
                return False
        for idx, (ar, er, edir) in enumerate(zip(actual.relationships, expected.rels, expected.directions)):
            if not _normalize_cell_for_cmp(ar, er, ignore_list_order=ignore_list_order):
                return False
            prev_n = actual.nodes[idx]
            next_n = actual.nodes[idx + 1]
            if edir == "out":
                if ar.src != prev_n.id or ar.dst != next_n.id:
                    return False
            elif edir == "in":
                if ar.dst != prev_n.id or ar.src != next_n.id:
                    return False
            else:
                if not ((ar.src == prev_n.id and ar.dst == next_n.id) or (ar.dst == prev_n.id and ar.src == next_n.id)):
                    return False
        return True

    # 9. List comparison (ordered unless ignore_list_order=True)
    if isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)):
            return False
        if len(actual) != len(expected):
            return False
        if not ignore_list_order:
            return all(_normalize_cell_for_cmp(a, e, ignore_list_order=False) for a, e in zip(actual, expected))
        unmatched = list(actual)
        for e in expected:
            found_idx = None
            for idx, a in enumerate(unmatched):
                if _normalize_cell_for_cmp(a, e, ignore_list_order=True):
                    found_idx = idx
                    break
            if found_idx is None:
                return False
            unmatched.pop(found_idx)
        return len(unmatched) == 0

    # 10. Map comparison
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return _compare_maps_strict(actual, expected, ignore_list_order=ignore_list_order)

    # 11. String comparison (exact match, no diagnostic regex normalization)
    if isinstance(expected, str):
        if isinstance(actual, str):
            return actual == expected
        if isinstance(actual, (Date, Time, DateTime, Duration)):
            return str(actual) == expected
        return False

    return False


def _compare_maps_strict(actual: dict[str, Any], expected: dict[str, Any], ignore_list_order: bool = False) -> bool:
    actual_keys = list(dict.keys(actual)) if isinstance(actual, dict) else list(actual.keys())
    if len(actual_keys) != len(expected) or set(actual_keys) != set(expected.keys()):
        return False
    for k, exp_v in expected.items():
        act_v = dict.__getitem__(actual, k) if isinstance(actual, dict) else actual[k]
        if not _normalize_cell_for_cmp(act_v, exp_v, ignore_list_order=ignore_list_order):
            return False
    return True


def _match_row(
    actual_row: dict[str, Any],
    expected_row: dict[str, Any],
    col_names: list[str],
    ignore_list_order: bool = False,
) -> bool:
    """Strict column and cell matching between an actual result row and expected row."""
    actual_keys = list(dict.keys(actual_row)) if isinstance(actual_row, dict) else list(actual_row.keys())
    if len(actual_keys) != len(expected_row) or set(actual_keys) != set(expected_row.keys()):
        return False
    if col_names and set(actual_keys) != set(col_names):
        return False
    for exp_col, exp_val in expected_row.items():
        act_val = dict.__getitem__(actual_row, exp_col) if isinstance(actual_row, dict) else actual_row[exp_col]
        if not _normalize_cell_for_cmp(act_val, exp_val, ignore_list_order=ignore_list_order):
            return False
    return True


def _serialize_val(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        if math.isnan(v):
            return "NaN"
        if math.isinf(v):
            return "Infinity" if v > 0 else "-Infinity"
        return v
    if isinstance(v, (ExpectedNode, ExpectedRel, ExpectedPath)):
        return repr(v)
    if hasattr(v, "nodes") and hasattr(v, "relationships"):
        parts = []
        for i, n in enumerate(v.nodes):
            lbls = ":".join(n.labels) if hasattr(n, "labels") and n.labels else (n.label if getattr(n, "label", None) and n.label != "Node" else "")
            lbl_str = f":{lbls}" if lbls else ""
            parts.append(f"({lbl_str} {n.props})" if getattr(n, "props", None) else f"({lbl_str})")
            if i < len(v.relationships):
                r = v.relationships[i]
                r_lbl = f":{r.label}" if getattr(r, "label", None) else ""
                if r.src == n.id:
                    parts.append(f"-[{r_lbl}]->")
                else:
                    parts.append(f"<-[{r_lbl}]-")
        return f"<{''.join(parts)}>"
    if hasattr(v, "id") and hasattr(v, "label") and hasattr(v, "props"):
        lbls = ":".join(v.labels) if hasattr(v, "labels") and v.labels else (v.label if v.label and v.label != "Node" else "")
        lbl_str = f":{lbls}" if lbls else ""
        return f"({lbl_str} {v.props})" if v.props else f"({lbl_str})"
    if hasattr(v, "src") and hasattr(v, "dst"):
        lbl_str = f":{v.label}" if getattr(v, "label", None) else ""
        return f"[{lbl_str} {v.props}]" if v.props else f"[{lbl_str}]"
    if isinstance(v, (list, tuple)):
        return [_serialize_val(x) for x in v]
    if isinstance(v, dict):
        return {k: _serialize_val(val) for k, val in dict.items(v)}
    return str(v)


def _serialize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: _serialize_val(v) for k, v in (dict.items(r) if isinstance(r, dict) else r.items())} for r in rows]


_EXPLICIT_ERROR_CATEGORY_MAP: dict[str, tuple[type[Exception], ...]] = {
    "SyntaxError": (LarkError, SyntaxError, SemanticError),
    "syntax_error": (LarkError, SyntaxError, SemanticError),
    "SemanticError": (SemanticError,),
    "semantic_error": (SemanticError,),
    "CompileTimeError": (SemanticError, SyntaxError, LarkError),
    "TypeError": (TypeError, TypeErrorDiagnostic),
    "type_error": (TypeError, TypeErrorDiagnostic),
    "ArgumentError": (ArgumentError, ValueError),
    "argument_error": (ArgumentError, ValueError),
    "EntityNotFound": (EntityNotFoundError,),
    "entity_not_found": (EntityNotFoundError,),
    "ConstraintVerificationFailed": (ConstraintVerificationError,),
    "constraint_error": (ConstraintVerificationError,),
    "ProcedureError": (ProcedureError,),
    "procedure_error": (ProcedureError,),
    "ParameterMissing": (ParameterMissingError,),
    "parameter_missing": (ParameterMissingError,),
}


def _is_matching_error(
    exc: Exception,
    expected_error_type: str | None,
    expected_phase: str | None = None,
    actual_phase: str | None = None,
) -> bool:
    """Strictly verify that `exc` matches both the expected error category and execution phase.

    Never matches generic `RuntimeError`, `KeyError`, `AttributeError`, `IndexError`,
    `ZeroDivisionError`, or arbitrary exceptions whose class name merely contains 'Error'.
    """
    if expected_phase in ("compile_time", "runtime") and actual_phase is not None:
        if expected_phase != actual_phase:
            return False

    if not expected_error_type:
        return False

    allowed_classes = _EXPLICIT_ERROR_CATEGORY_MAP.get(expected_error_type)
    if not allowed_classes:
        return False

    return isinstance(exc, allowed_classes)


def _execute_query_with_phase(query_str: str, graph: PropertyGraph) -> list[dict[str, Any]]:
    """Execute query while tracking whether an exception occurs at compile time or runtime.

    Raises `(exc, phase)` wrapped in `_PhasedQueryError`.
    """
    try:
        query_ast = parse(query_str)
        validate_query(query_ast)
    except Exception as exc:
        raise _PhasedQueryError(exc, "compile_time") from exc

    try:
        if _is_pipeline_query(query_ast):
            return execute_pipeline(query_ast, graph)
        try:
            plan_obj = plan_query(query_ast, graph)
        except Exception:
            if query_ast.clauses:
                return execute_pipeline(query_ast, graph)
            raise
        return execute(plan_obj, graph)
    except Exception as exc:
        raise _PhasedQueryError(exc, "runtime") from exc


class _PhasedQueryError(Exception):
    def __init__(self, original: Exception, phase: str) -> None:
        super().__init__(str(original))
        self.original = original
        self.phase = phase


def _verify_result_set(
    rows: list[dict[str, Any]],
    expected_kind: str,
    expected_rows: list[dict[str, Any]],
    expected_columns: list[str],
    in_order: bool,
    ignore_list_order: bool,
    scenario: TCKScenario,
    label_prefix: str = "",
) -> dict[str, Any] | None:
    """Verify result rows against expectations. Returns a failure dict on mismatch, or None if valid."""
    prefix = f"{label_prefix}: " if label_prefix else ""
    if expected_kind == "empty":
        if len(rows) != 0:
            return {
                "scenario_id": scenario.scenario_id,
                "feature": scenario.feature,
                "name": scenario.name,
                "primary_classification": "FAIL_WRONG_RESULT",
                "status": "failed",
                "reason": f"{prefix}Expected empty result but got {len(rows)} rows",
                "query": scenario.query,
                "expected_kind": scenario.expected_kind,
                "expected_rows": [],
                "actual_rows": _serialize_rows(rows[:5]),
            }
        return None

    # Check column names even when 0 rows are returned if columns are inspectable on rows
    if len(rows) != len(expected_rows):
        return {
            "scenario_id": scenario.scenario_id,
            "feature": scenario.feature,
            "name": scenario.name,
            "primary_classification": "FAIL_WRONG_RESULT",
            "status": "failed",
            "reason": f"{prefix}Row count mismatch: expected {len(expected_rows)}, got {len(rows)}",
            "query": scenario.query,
            "expected_kind": scenario.expected_kind,
            "expected_rows": _serialize_rows(expected_rows),
            "actual_rows": _serialize_rows(rows[:5]),
        }

    if in_order:
        for idx, (act, exp) in enumerate(zip(rows, expected_rows)):
            if not _match_row(act, exp, expected_columns, ignore_list_order=ignore_list_order):
                return {
                    "scenario_id": scenario.scenario_id,
                    "feature": scenario.feature,
                    "name": scenario.name,
                    "primary_classification": "FAIL_WRONG_RESULT",
                    "status": "failed",
                    "reason": f"{prefix}Ordered row mismatch at index {idx}: expected {_serialize_val(exp)}, got {_serialize_val(act)}",
                    "query": scenario.query,
                    "expected_kind": scenario.expected_kind,
                    "expected_rows": _serialize_rows(expected_rows),
                    "actual_rows": _serialize_rows(rows[:5]),
                }
    else:
        unmatched_expected = list(expected_rows)
        for act in rows:
            found_idx = None
            for idx, exp in enumerate(unmatched_expected):
                if _match_row(act, exp, expected_columns, ignore_list_order=ignore_list_order):
                    found_idx = idx
                    break
            if found_idx is not None:
                unmatched_expected.pop(found_idx)
            else:
                return {
                    "scenario_id": scenario.scenario_id,
                    "feature": scenario.feature,
                    "name": scenario.name,
                    "primary_classification": "FAIL_WRONG_RESULT",
                    "status": "failed",
                    "reason": f"{prefix}Actual row {_serialize_val(act)} did not match any remaining expected row in {_serialize_rows(unmatched_expected[:3])}",
                    "query": scenario.query,
                    "expected_kind": scenario.expected_kind,
                    "expected_rows": _serialize_rows(expected_rows),
                    "actual_rows": _serialize_rows(rows[:5]),
                }
    return None


def run_scenario(scenario: TCKScenario, relaxed_columns: bool = False) -> dict[str, Any]:
    """Execute a single TCK scenario and return classification & result status.

    Note: `relaxed_columns` is retained only for backward-compatible signature; strict column
    matching is always enforced.
    """
    # 0. Block scenarios with uninterpreted / unknown Gherkin steps
    if scenario.parse_errors:
        return {
            "scenario_id": scenario.scenario_id,
            "feature": scenario.feature,
            "name": scenario.name,
            "primary_classification": "BLOCKED",
            "status": "blocked",
            "reason": f"Uninterpreted Gherkin step(s): {'; '.join(scenario.parse_errors)}",
            "query": scenario.query,
            "expected_kind": scenario.expected_kind,
            "expected_rows": _serialize_rows(scenario.expected_rows),
            "actual_rows": [],
        }

    # 1. Check if within declared language subset
    is_supported, unsupp_reason = classify_query(scenario.query)
    if not is_supported:
        return {
            "scenario_id": scenario.scenario_id,
            "feature": scenario.feature,
            "name": scenario.name,
            "primary_classification": "UNSUPPORTED",
            "status": "unsupported",
            "reason": unsupp_reason,
            "query": scenario.query,
            "expected_kind": scenario.expected_kind,
            "expected_rows": _serialize_rows(scenario.expected_rows),
            "actual_rows": [],
        }

    # 2. Construct test fixture graph BEFORE query execution (for both result and error scenarios!)
    # Any failure during fixture setup MUST produce BLOCKED, never PASS_EXPECTED_ERROR.
    graph = PropertyGraph()
    graph._procedures = dict(scenario.procedures)
    graph._parameters = dict(scenario.parameters)
    try:
        if scenario.named_graph:
            _load_named_graph(scenario.named_graph, graph)
        for create_stmt in scenario.background_create:
            load_cypher_create_fixture(create_stmt, graph)
        for create_stmt in scenario.scenario_create:
            load_cypher_create_fixture(create_stmt, graph)
    except Exception as e:
        return {
            "scenario_id": scenario.scenario_id,
            "feature": scenario.feature,
            "name": scenario.name,
            "primary_classification": "BLOCKED",
            "status": "blocked",
            "reason": f"Fixture creation error: {type(e).__name__} - {e}",
            "query": scenario.query,
            "expected_kind": scenario.expected_kind,
            "expected_rows": _serialize_rows(scenario.expected_rows),
            "actual_rows": [],
        }

    is_error_expectation = scenario.expected_error_type is not None or scenario.expected_kind in (
        "syntax_error",
        "semantic_error",
        "type_error",
        "procedure_error",
        "argument_error",
        "constraint_error",
        "entity_not_found",
        "parameter_missing",
        "error",
    )

    # 3. Handle expected-error scenarios with strict category and phase verification
    if is_error_expectation:
        expected_err_key = scenario.expected_error_type or scenario.expected_kind
        expected_phase = scenario.expected_error_phase
        try:
            rows = _execute_query_with_phase(scenario.query, graph)
            return {
                "scenario_id": scenario.scenario_id,
                "feature": scenario.feature,
                "name": scenario.name,
                "primary_classification": "FAIL_WRONG_RESULT",
                "status": "failed",
                "reason": f"Expected {expected_err_key} (phase={expected_phase}) but query succeeded without error",
                "query": scenario.query,
                "expected_kind": scenario.expected_kind,
                "expected_rows": [],
                "actual_rows": _serialize_rows(rows) if isinstance(rows, list) else [],
            }
        except _PhasedQueryError as pe:
            exc = pe.original
            actual_phase = pe.phase
            if _is_matching_error(exc, expected_err_key, expected_phase, actual_phase):
                return {
                    "scenario_id": scenario.scenario_id,
                    "feature": scenario.feature,
                    "name": scenario.name,
                    "primary_classification": "PASS_EXPECTED_ERROR",
                    "status": "passed",
                    "reason": f"Correctly raised {type(exc).__name__} at {actual_phase} for expected {expected_err_key} ({expected_phase}): {exc}",
                    "query": scenario.query,
                    "expected_kind": scenario.expected_kind,
                    "expected_rows": [],
                    "actual_rows": [],
                }
            else:
                fail_type = "FAIL_COMPILE" if actual_phase == "compile_time" else "FAIL_RUNTIME"
                return {
                    "scenario_id": scenario.scenario_id,
                    "feature": scenario.feature,
                    "name": scenario.name,
                    "primary_classification": fail_type,
                    "error_mismatch": True,
                    "status": "failed",
                    "reason": (
                        f"Raised {type(exc).__name__} at {actual_phase}, which did not match "
                        f"expected {expected_err_key} at {expected_phase or 'any_time'}: {exc}"
                    ),
                    "query": scenario.query,
                    "expected_kind": scenario.expected_kind,
                    "expected_rows": [],
                    "actual_rows": [],
                }

    # 4. Snapshot graph state after fixture setup and before query under test
    before_snapshot = _snapshot_graph(graph)

    # 5. Execute query under test
    try:
        rows = _execute_query_with_phase(scenario.query, graph)
    except _PhasedQueryError as pe:
        exc = pe.original
        fail_type = "FAIL_COMPILE" if pe.phase == "compile_time" else "FAIL_RUNTIME"
        return {
            "scenario_id": scenario.scenario_id,
            "feature": scenario.feature,
            "name": scenario.name,
            "primary_classification": fail_type,
            "status": "failed",
            "reason": f"Execution exception ({pe.phase}): {type(exc).__name__} - {exc}",
            "query": scenario.query,
            "expected_kind": scenario.expected_kind,
            "expected_rows": _serialize_rows(scenario.expected_rows),
            "actual_rows": [],
            "traceback": traceback.format_exc(),
        }

    # 6. Snapshot graph state immediately after tested query (before any control query)
    after_snapshot = _snapshot_graph(graph)
    actual_side_effects = _compute_side_effects(before_snapshot, after_snapshot)

    # 7. Verify primary query result
    res_err = _verify_result_set(
        rows=rows,
        expected_kind=scenario.expected_kind,
        expected_rows=scenario.expected_rows,
        expected_columns=scenario.expected_columns,
        in_order=scenario.in_order,
        ignore_list_order=scenario.ignore_list_order,
        scenario=scenario,
    )
    if res_err is not None:
        return res_err

    # 8. Verify mutation side effects (`And no side effects` or `And the side effects should be:`)
    side_effect_checked = False
    if scenario.expect_no_side_effects or scenario.expected_side_effects is not None:
        side_effect_checked = True
        expected_se = {} if scenario.expect_no_side_effects else (scenario.expected_side_effects or {})
        if actual_side_effects != expected_se:
            return {
                "scenario_id": scenario.scenario_id,
                "feature": scenario.feature,
                "name": scenario.name,
                "primary_classification": "FAIL_WRONG_RESULT",
                "side_effect_failure": True,
                "status": "failed",
                "reason": f"Side-effect mismatch: expected {expected_se}, got {actual_side_effects}",
                "query": scenario.query,
                "expected_kind": scenario.expected_kind,
                "expected_rows": _serialize_rows(scenario.expected_rows),
                "actual_rows": _serialize_rows(rows[:5]),
                "expected_side_effects": expected_se,
                "actual_side_effects": actual_side_effects,
            }

    # 9. Execute and verify control query if present
    if scenario.control_query:
        try:
            ctrl_rows = _execute_query_with_phase(scenario.control_query, graph)
        except _PhasedQueryError as pe:
            exc = pe.original
            fail_type = "FAIL_COMPILE" if pe.phase == "compile_time" else "FAIL_RUNTIME"
            return {
                "scenario_id": scenario.scenario_id,
                "feature": scenario.feature,
                "name": scenario.name,
                "primary_classification": fail_type,
                "status": "failed",
                "reason": f"Control query exception ({pe.phase}): {type(exc).__name__} - {exc}",
                "query": scenario.query,
                "expected_kind": scenario.expected_kind,
                "expected_rows": _serialize_rows(scenario.control_expected_rows),
                "actual_rows": [],
            }
        ctrl_err = _verify_result_set(
            rows=ctrl_rows,
            expected_kind=scenario.control_expected_kind or "result",
            expected_rows=scenario.control_expected_rows,
            expected_columns=scenario.control_expected_columns,
            in_order=scenario.control_in_order,
            ignore_list_order=scenario.control_ignore_list_order,
            scenario=scenario,
            label_prefix="Control query",
        )
        if ctrl_err is not None:
            return ctrl_err

    return {
        "scenario_id": scenario.scenario_id,
        "feature": scenario.feature,
        "name": scenario.name,
        "primary_classification": "PASS_RESULT",
        "side_effect_checked": side_effect_checked,
        "has_mutation_side_effects": bool(scenario.expected_side_effects),
        "status": "passed",
        "reason": f"Exact match on {len(rows)} rows (in_order={scenario.in_order}, side_effects={actual_side_effects})",
        "query": scenario.query,
        "expected_kind": scenario.expected_kind,
        "expected_rows": _serialize_rows(scenario.expected_rows),
        "actual_rows": _serialize_rows(rows[:5]),
    }
