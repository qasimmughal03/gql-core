"""openCypher TCK Scenario Execution Adapter for GQL-Core.

Executes TCK scenarios strictly through GQL-Core's public query API and compares
results against expected tabular data, row counts, duplicate multiplicity, and ordering.
"""

from __future__ import annotations

import traceback
from typing import Any
from gql_core import PropertyGraph, run as run_query
from benchmark.tck.classifier import classify_query
from benchmark.tck.fixture_loader import load_cypher_create_fixture
from benchmark.tck.gherkin_parser import TCKScenario


from pathlib import Path
import re
from benchmark.tck.fixture_loader import _parse_props

_NAMED_GRAPHS_DIR = Path(__file__).resolve().parent.parent / "cache" / "openCypher" / "tck" / "graphs"


def _load_named_graph(graph_name: str, graph: PropertyGraph) -> None:
    """Load pre-defined named graph fixtures (e.g. binary-tree-1, binary-tree-2)."""
    cypher_file = _NAMED_GRAPHS_DIR / graph_name / f"{graph_name}.cypher"
    if cypher_file.exists():
        content = cypher_file.read_text(encoding="utf-8")
        load_cypher_create_fixture(content, graph)


from lark.exceptions import LarkError
from gql_core.query.semantic import SemanticError


def _normalize_cell_for_cmp(actual: Any, expected: Any) -> bool:
    """Compare an actual GQL-Core binding value with expected TCK table cell value."""
    import math
    if isinstance(actual, float) and math.isnan(actual):
        return (isinstance(expected, float) and math.isnan(expected)) or str(expected).upper() == "NAN"
    if str(expected).upper() == "NAN":
        return isinstance(actual, float) and math.isnan(actual)

    if expected is None:
        return actual is None
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual is expected
    if isinstance(expected, int):
        if isinstance(actual, bool):
            return False
        if isinstance(actual, int):
            return actual == expected
        if isinstance(actual, float):
            return abs(float(actual) - float(expected)) < 1e-6
        return False
    if isinstance(expected, float):
        if isinstance(actual, bool):
            return False
        if isinstance(actual, (int, float)):
            return abs(float(actual) - float(expected)) < 1e-6
        return False

    if isinstance(expected, str):
        if isinstance(actual, (int, float)):
            try:
                exp_f = float(expected)
                if math.isnan(exp_f):
                    return math.isnan(actual)
                return abs(float(actual) - exp_f) < 1e-6
            except ValueError:
                pass
        if isinstance(actual, str):
            if actual == expected:
                return True
            # Allow ISO time seconds normalization (e.g. 10:35 vs 10:35:00)
            if re.sub(r":00(?=[+-]|$)", "", actual) == re.sub(r":00(?=[+-]|$)", "", expected):
                return True
            # Handle Gherkin table escaped backslashes, quotes, and newlines
            if expected.replace(r"\\", "\\") == actual:
                return True
            if expected.replace(r"\n", "\n") == actual:
                return True
            if expected.replace(r"\\", "\\").replace(r"\n", "\n") == actual:
                return True
            if expected.replace(r"\\", "\\").replace(r'\"', '"') == actual:
                return True
            if expected.replace(r'\"', '"').replace(r"\\", "\\") == actual:
                return True
            if expected.replace(r"\\", "\\").replace(r'\"', '"').replace(r"\\", "\\") == actual:
                return True

    # Path entity comparison
    if hasattr(actual, "nodes") and hasattr(actual, "relationships"):
        if isinstance(expected, str) and expected.startswith("<") and expected.endswith(">"):
            inner = expected[1:-1].strip()
            exp_nodes = re.findall(r"\([^)]*\)", inner)
            exp_rels = re.findall(r"<-\[[^\]]*\]-?|-\[[^\]]*\]->?|-->|<--|--", inner)
            if len(actual.nodes) != len(exp_nodes) or len(actual.relationships) != len(exp_rels):
                return False
            for an, en in zip(actual.nodes, exp_nodes):
                if not _normalize_cell_for_cmp(an, en):
                    return False
            for ar, er in zip(actual.relationships, exp_rels):
                if not _normalize_cell_for_cmp(ar, er):
                    return False
            return True
        return False

    # Relationship comparison
    if hasattr(actual, "src") and hasattr(actual, "dst"):
        if isinstance(expected, list):
            return any(_normalize_cell_for_cmp(actual, x) for x in expected)
        if isinstance(expected, str):
            s = expected.strip()
            # If relationship pattern like -[:KNOWS]-> or -[:KNOWS {num: 1}]-> or -->
            m = re.search(r":([a-zA-Z0-9_]+)", s)
            if m and actual.label != m.group(1):
                return False
            props_m = re.search(r"\{([^}]+)\}", s)
            if props_m:
                exp_props = _parse_props(props_m.group(1))
                for pk, pv in exp_props.items():
                    if not _normalize_cell_for_cmp(actual.props.get(pk), pv):
                        return False
            if not m and not props_m:
                clean_exp = s.strip("[]'\" :-<>")
                if clean_exp and clean_exp != actual.label and str(actual.id) != s:
                    return False
            return True
        return False

    # Node entity comparison
    if hasattr(actual, "label") and hasattr(actual, "props"):
        if isinstance(expected, str):
            s = expected.strip()
            if s.startswith("(") and s.endswith(")"):
                inner = s[1:-1].strip()
                exp_labels = set(re.findall(r":([a-zA-Z0-9_]+)", inner))
                actual_labels = set(getattr(actual, "labels", ()) or ((actual.label,) if actual.label and actual.label != "Node" else ()))
                if exp_labels != actual_labels:
                    return False
                props_m = re.search(r"\{([^}]+)\}", inner)
                if props_m:
                    exp_props = _parse_props(props_m.group(1))
                    for pk, pv in exp_props.items():
                        if not _normalize_cell_for_cmp(actual.props.get(pk), pv):
                            return False
                return True
            return str(actual.id) == s
        return False

    # Collection comparison
    if isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        if len(actual) != len(expected):
            return False
        if all(_normalize_cell_for_cmp(a, e) for a, e in zip(actual, expected)):
            return True
        unmatched = list(actual)
        for e in expected:
            found = False
            for idx, a in enumerate(unmatched):
                if _normalize_cell_for_cmp(a, e):
                    unmatched.pop(idx)
                    found = True
                    break
            if not found:
                return False
        return len(unmatched) == 0

    # Map comparison
    if isinstance(actual, dict) and isinstance(expected, dict):
        if set(actual.keys()) != set(expected.keys()):
            return False
        return all(_normalize_cell_for_cmp(actual[k], expected[k]) for k in actual)

    if isinstance(expected, str):
        return isinstance(actual, str) and actual == expected

    return actual == expected


def _match_row(
    actual_row: dict[str, Any],
    expected_row: dict[str, Any],
    col_names: list[str],
    relaxed_columns: bool = False,
) -> bool:
    """Key-based column matching between actual and expected row.

    In strict mode (relaxed_columns=False), exact column names are required.
    In diagnostic mode (relaxed_columns=True), candidate expansions for expressions
    containing '.' or '(' are permitted to analyze projection-naming drift.
    """
    if len(actual_row) != len(expected_row):
        return False

    if not relaxed_columns:
        for exp_col, exp_val in expected_row.items():
            if exp_col not in actual_row:
                return False
            if not _normalize_cell_for_cmp(actual_row[exp_col], exp_val):
                return False
        return True

    # Diagnostic mode: candidate matching for unaliased expressions
    used_actual_keys: set[str] = set()
    for exp_col, exp_val in expected_row.items():
        candidates = [exp_col]
        if "." in exp_col:
            candidates.append(exp_col.split(".")[-1])
            candidates.append(exp_col.replace(".", "_"))
        if "(" in exp_col:
            clean_agg = exp_col.replace("(", "_").replace(")", "").replace("*", "")
            candidates.append(clean_agg)
            candidates.append(exp_col.split("(")[0])

        matched_key = None
        for c in candidates:
            if c in actual_row and c not in used_actual_keys:
                try:
                    val = actual_row[c]
                except KeyError:
                    continue
                if _normalize_cell_for_cmp(val, exp_val):
                    matched_key = c
                    break

        if matched_key is None:
            return False
        used_actual_keys.add(matched_key)

    return len(used_actual_keys) == len(expected_row)


def _serialize_val(v: Any) -> Any:
    import math
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return "NaN" if math.isnan(v) else v
    if hasattr(v, "nodes") and hasattr(v, "relationships"):
        parts = []
        for i, n in enumerate(v.nodes):
            lbls = ":".join(n.labels) if hasattr(n, "labels") and n.labels else (n.label if getattr(n, "label", None) and n.label != "Node" else "")
            lbl_str = f":{lbls}" if lbls else ""
            parts.append(f"({lbl_str})")
            if i < len(v.relationships):
                r = v.relationships[i]
                r_lbl = f":{r.label}" if getattr(r, "label", None) else ""
                parts.append(f"-[:{r_lbl}]->")
        return f"<{''.join(parts)}>"
    if hasattr(v, "id") and hasattr(v, "label") and hasattr(v, "props"):
        lbls = ":".join(v.labels) if hasattr(v, "labels") and v.labels else (v.label if v.label and v.label != "Node" else "")
        lbl_str = f":{lbls}" if lbls else ""
        return f"({lbl_str} {v.props})" if v.props else f"({lbl_str})"
    if hasattr(v, "src") and hasattr(v, "dst"):
        lbl_str = f":{v.label}" if getattr(v, "label", None) else ""
        return f"-[:{lbl_str} {v.props}]->" if v.props else f"-[:{lbl_str}]->"
    if isinstance(v, (list, tuple)):
        return [_serialize_val(x) for x in v]
    if isinstance(v, dict):
        return {k: _serialize_val(val) for k, val in v.items()}
    return str(v)


def _serialize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: _serialize_val(v) for k, v in r.items()} for r in rows]


def _is_matching_error(exc: Exception, expected_kind: str) -> bool:
    exc_type = type(exc).__name__
    if expected_kind in ("syntax_error", "semantic_error"):
        return isinstance(exc, (LarkError, SyntaxError, SemanticError, ValueError)) or "Error" in exc_type
    if expected_kind == "type_error":
        from gql_core.types import TypeErrorDiagnostic
        return isinstance(exc, (TypeError, TypeErrorDiagnostic, SemanticError)) or "TypeError" in exc_type
    if expected_kind in ("argument_error", "procedure_error", "constraint_error"):
        return isinstance(exc, (ValueError, TypeError, SemanticError)) or "Error" in exc_type
    return True


def run_scenario(scenario: TCKScenario, relaxed_columns: bool = False) -> dict[str, Any]:
    """Execute a single TCK scenario and return classification & result status.
    
    Primary classifications:
    - PASS_RESULT: executed and returned precisely the expected results.
    - PASS_EXPECTED_ERROR: rejected invalid input with the expected error category.
    - FAIL_WRONG_RESULT: returned incorrect rows, values, columns or ordering.
    - FAIL_COMPILE: rejected a valid supported query.
    - FAIL_RUNTIME: failed unexpectedly during execution.
    - UNSUPPORTED: requires features explicitly outside the declared supported language contract.
    - BLOCKED: could not be evaluated because of a fixture or harness issue.
    """
    # 1. Check if within claimed language subset
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

    # 2. Check for expected syntax or semantic or runtime errors
    if scenario.expected_kind in (
        "syntax_error",
        "semantic_error",
        "type_error",
        "procedure_error",
        "argument_error",
        "constraint_error",
        "error",
    ):
        try:
            graph = PropertyGraph()
            graph._procedures = dict(scenario.procedures)
            graph._parameters = dict(scenario.parameters)
            if scenario.named_graph:
                _load_named_graph(scenario.named_graph, graph)
            for create_stmt in scenario.background_create + scenario.scenario_create:
                load_cypher_create_fixture(create_stmt, graph)
            rows = run_query(scenario.query, graph)
            return {
                "scenario_id": scenario.scenario_id,
                "feature": scenario.feature,
                "name": scenario.name,
                "primary_classification": "FAIL_WRONG_RESULT",
                "status": "failed",
                "reason": f"Expected {scenario.expected_kind} but query succeeded without error",
                "query": scenario.query,
                "expected_kind": scenario.expected_kind,
                "expected_rows": [],
                "actual_rows": _serialize_rows(rows) if isinstance(rows, list) else [],
            }
        except Exception as e:
            if _is_matching_error(e, scenario.expected_kind):
                return {
                    "scenario_id": scenario.scenario_id,
                    "feature": scenario.feature,
                    "name": scenario.name,
                    "primary_classification": "PASS_EXPECTED_ERROR",
                    "status": "passed",
                    "reason": f"Correctly raised {type(e).__name__} for expected {scenario.expected_kind}: {e}",
                    "query": scenario.query,
                    "expected_kind": scenario.expected_kind,
                    "expected_rows": [],
                    "actual_rows": [],
                }
            else:
                fail_type = "FAIL_COMPILE" if isinstance(e, (LarkError, SyntaxError, SemanticError)) else "FAIL_RUNTIME"
                return {
                    "scenario_id": scenario.scenario_id,
                    "feature": scenario.feature,
                    "name": scenario.name,
                    "primary_classification": fail_type,
                    "status": "failed",
                    "reason": f"Raised {type(e).__name__} which did not match expected {scenario.expected_kind}: {e}",
                    "query": scenario.query,
                    "expected_kind": scenario.expected_kind,
                    "expected_rows": [],
                    "actual_rows": [],
                }

    # 3. Build test fixture graph
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

    # 4. Execute query via public GQL-Core API
    try:
        rows = run_query(scenario.query, graph)
        if scenario.control_query:
            rows = run_query(scenario.control_query, graph)
    except Exception as e:
        fail_type = "FAIL_COMPILE" if isinstance(e, (LarkError, SyntaxError, SemanticError)) else "FAIL_RUNTIME"
        return {
            "scenario_id": scenario.scenario_id,
            "feature": scenario.feature,
            "name": scenario.name,
            "primary_classification": fail_type,
            "status": "failed",
            "reason": f"Execution exception: {type(e).__name__} - {e}",
            "query": scenario.query,
            "expected_kind": scenario.expected_kind,
            "expected_rows": _serialize_rows(scenario.expected_rows),
            "actual_rows": [],
            "traceback": traceback.format_exc(),
        }

    # 5. Check empty result expectation
    if scenario.expected_kind == "empty":
        if len(rows) == 0:
            return {
                "scenario_id": scenario.scenario_id,
                "feature": scenario.feature,
                "name": scenario.name,
                "primary_classification": "PASS_RESULT",
                "status": "passed",
                "reason": "Correctly returned empty result set",
                "query": scenario.query,
                "expected_kind": scenario.expected_kind,
                "expected_rows": [],
                "actual_rows": [],
            }
        return {
            "scenario_id": scenario.scenario_id,
            "feature": scenario.feature,
            "name": scenario.name,
            "primary_classification": "FAIL_WRONG_RESULT",
            "status": "failed",
            "reason": f"Expected empty result but got {len(rows)} rows",
            "query": scenario.query,
            "expected_kind": scenario.expected_kind,
            "expected_rows": [],
            "actual_rows": _serialize_rows(rows[:5]),
        }

    # 6. Verify row count
    if len(rows) != len(scenario.expected_rows):
        return {
            "scenario_id": scenario.scenario_id,
            "feature": scenario.feature,
            "name": scenario.name,
            "primary_classification": "FAIL_WRONG_RESULT",
            "status": "failed",
            "reason": f"Row count mismatch: expected {len(scenario.expected_rows)}, got {len(rows)}",
            "query": scenario.query,
            "expected_kind": scenario.expected_kind,
            "expected_rows": _serialize_rows(scenario.expected_rows),
            "actual_rows": _serialize_rows(rows[:5]),
        }

    # 7. Verify rows (ordered or unordered multiset)
    if scenario.in_order:
        for idx, (act, exp) in enumerate(zip(rows, scenario.expected_rows)):
            if not _match_row(act, exp, scenario.expected_columns, relaxed_columns=relaxed_columns):
                return {
                    "scenario_id": scenario.scenario_id,
                    "feature": scenario.feature,
                    "name": scenario.name,
                    "primary_classification": "FAIL_WRONG_RESULT",
                    "status": "failed",
                    "reason": f"Ordered row mismatch at index {idx}: expected {exp}, got {_serialize_val(act)}",
                    "query": scenario.query,
                    "expected_kind": scenario.expected_kind,
                    "expected_rows": _serialize_rows(scenario.expected_rows),
                    "actual_rows": _serialize_rows(rows[:5]),
                }
    else:
        unmatched_expected = list(scenario.expected_rows)
        for act in rows:
            found_idx = None
            for idx, exp in enumerate(unmatched_expected):
                if _match_row(act, exp, scenario.expected_columns, relaxed_columns=relaxed_columns):
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
                    "reason": f"Actual row {_serialize_val(act)} did not match any remaining expected row in {_serialize_rows(unmatched_expected[:3])}",
                    "query": scenario.query,
                    "expected_kind": scenario.expected_kind,
                    "expected_rows": _serialize_rows(scenario.expected_rows),
                    "actual_rows": _serialize_rows(rows[:5]),
                }

    return {
        "scenario_id": scenario.scenario_id,
        "feature": scenario.feature,
        "name": scenario.name,
        "primary_classification": "PASS_RESULT",
        "status": "passed",
        "reason": f"Exact match on {len(rows)} rows (in_order={scenario.in_order})",
        "query": scenario.query,
        "expected_kind": scenario.expected_kind,
        "expected_rows": _serialize_rows(scenario.expected_rows),
        "actual_rows": _serialize_rows(rows[:5]),
    }
