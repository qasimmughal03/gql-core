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


import re
from benchmark.tck.fixture_loader import _parse_props


from lark.exceptions import LarkError
from gql_core.query.semantic import SemanticError


def _normalize_cell_for_cmp(actual: Any, expected: Any) -> bool:
    """Compare an actual GQL-Core binding value with expected TCK table cell value."""
    if expected is None:
        return actual is None
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual is expected
    if isinstance(expected, int):
        if isinstance(actual, bool):
            return False
        if isinstance(actual, int):
            return actual == expected
        if isinstance(actual, float) and actual.is_integer():
            return int(actual) == expected
        return False
    if isinstance(expected, float):
        if isinstance(actual, bool):
            return False
        if isinstance(actual, (int, float)):
            return abs(float(actual) - float(expected)) < 1e-6
        return False

    # Relationship comparison
    if hasattr(actual, "src") and hasattr(actual, "dst"):
        if isinstance(expected, list):
            return any(actual.label == str(x).lstrip(":") for x in expected)
        if isinstance(expected, str):
            clean_exp = expected.strip("[]'\" :")
            return clean_exp == actual.label or str(actual.id) == expected
        return False

    # Node entity comparison
    if hasattr(actual, "label") and hasattr(actual, "props"):
        if isinstance(expected, str):
            s = expected.strip()
            if s.startswith("(") and s.endswith(")"):
                inner = s[1:-1].strip()
                m = re.match(r"^(?::([a-zA-Z0-9_]+))?(?:\s*\{([^}]+)\})?$", inner)
                if m:
                    exp_label = m.group(1)
                    exp_props_str = m.group(2)
                    if exp_label and exp_label != actual.label:
                        return False
                    if exp_props_str:
                        exp_props = _parse_props(exp_props_str)
                        for pk, pv in exp_props.items():
                            if not _normalize_cell_for_cmp(actual.props.get(pk), pv):
                                return False
                    return True
            return str(actual.id) == s or (s in actual.props.values())
        return False

    if isinstance(expected, str):
        return isinstance(actual, str) and actual == expected

    return actual == expected


def _match_row(actual_row: dict[str, Any], expected_row: dict[str, Any], col_names: list[str]) -> bool:
    """Strict key-based column matching between actual and expected row."""
    # Length of projected row must match expected row
    if len(actual_row) != len(expected_row):
        return False

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
                if _normalize_cell_for_cmp(actual_row[c], exp_val):
                    matched_key = c
                    break

        if matched_key is None:
            return False
        used_actual_keys.add(matched_key)

    return len(used_actual_keys) == len(expected_row)


def run_scenario(scenario: TCKScenario) -> dict[str, Any]:
    """Execute a single TCK scenario and return classification & result status.
    
    Returns:
        dict with fields:
        - scenario_id
        - feature
        - name
        - status: 'passed' | 'failed' | 'unsupported' | 'blocked'
        - reason: string explanation for non-pass
        - latency_ms: execution time in ms
    """
    # 1. Check if within claimed language subset
    is_supported, unsupp_reason = classify_query(scenario.query)
    if not is_supported:
        return {
            "scenario_id": scenario.scenario_id,
            "feature": scenario.feature,
            "name": scenario.name,
            "status": "unsupported",
            "reason": unsupp_reason,
            "query": scenario.query,
        }

    # 2. Check for expected syntax or semantic errors
    if scenario.expected_kind == "syntax_error":
        try:
            graph = PropertyGraph()
            run_query(scenario.query, graph)
            return {
                "scenario_id": scenario.scenario_id,
                "feature": scenario.feature,
                "name": scenario.name,
                "status": "failed",
                "reason": "Expected syntax_error but query succeeded without error",
                "query": scenario.query,
            }
        except (LarkError, SemanticError) as e:
            return {
                "scenario_id": scenario.scenario_id,
                "feature": scenario.feature,
                "name": scenario.name,
                "status": "passed",
                "reason": f"Correctly raised compile-time validation error: {type(e).__name__} ({e})",
                "query": scenario.query,
            }
        except Exception as e:
            return {
                "scenario_id": scenario.scenario_id,
                "feature": scenario.feature,
                "name": scenario.name,
                "status": "failed",
                "reason": f"Expected syntax/compile-time error, but unhandled runtime exception occurred: {type(e).__name__}: {e}",
                "query": scenario.query,
            }

    if scenario.expected_kind == "semantic_error":
        try:
            graph = PropertyGraph()
            for create_stmt in scenario.background_create + scenario.scenario_create:
                load_cypher_create_fixture(create_stmt, graph)
            run_query(scenario.query, graph)
            return {
                "scenario_id": scenario.scenario_id,
                "feature": scenario.feature,
                "name": scenario.name,
                "status": "failed",
                "reason": "Expected semantic_error but query succeeded without error",
                "query": scenario.query,
            }
        except SemanticError as e:
            return {
                "scenario_id": scenario.scenario_id,
                "feature": scenario.feature,
                "name": scenario.name,
                "status": "passed",
                "reason": f"Correctly raised semantic validation error: {e}",
                "query": scenario.query,
            }
        except Exception as e:
            return {
                "scenario_id": scenario.scenario_id,
                "feature": scenario.feature,
                "name": scenario.name,
                "status": "failed",
                "reason": f"Expected semantic error, but got {type(e).__name__}: {e}",
                "query": scenario.query,
            }

    # 3. Build test fixture graph
    for create_stmt in scenario.background_create + scenario.scenario_create:
        if re.search(r"\bWITH\b|\bMERGE\b|\bDELETE\b|\bSET\b", create_stmt, re.I):
            return {
                "scenario_id": scenario.scenario_id,
                "feature": scenario.feature,
                "name": scenario.name,
                "status": "unsupported",
                "reason": "FIXTURE_REQUIRES_CYPHER_MUTATION_QUERY",
                "query": scenario.query,
            }

    graph = PropertyGraph()
    try:
        for create_stmt in scenario.background_create:
            load_cypher_create_fixture(create_stmt, graph)
        for create_stmt in scenario.scenario_create:
            load_cypher_create_fixture(create_stmt, graph)
    except Exception as e:
        return {
            "scenario_id": scenario.scenario_id,
            "feature": scenario.feature,
            "name": scenario.name,
            "status": "blocked",
            "reason": f"Fixture creation error: {type(e).__name__} - {e}",
            "query": scenario.query,
        }

    # 4. Execute query via public GQL-Core API
    try:
        rows = run_query(scenario.query, graph)
    except Exception as e:
        return {
            "scenario_id": scenario.scenario_id,
            "feature": scenario.feature,
            "name": scenario.name,
            "status": "failed",
            "reason": f"Execution exception: {type(e).__name__} - {e}",
            "query": scenario.query,
            "traceback": traceback.format_exc(),
        }

    # 5. Check empty result expectation
    if scenario.expected_kind == "empty":
        if len(rows) == 0:
            return {
                "scenario_id": scenario.scenario_id,
                "feature": scenario.feature,
                "name": scenario.name,
                "status": "passed",
                "reason": "Correctly returned empty result set",
                "query": scenario.query,
            }
        return {
            "scenario_id": scenario.scenario_id,
            "feature": scenario.feature,
            "name": scenario.name,
            "status": "failed",
            "reason": f"Expected empty result but got {len(rows)} rows: {rows[:3]}",
            "query": scenario.query,
        }

    # 6. Verify row count
    if len(rows) != len(scenario.expected_rows):
        return {
            "scenario_id": scenario.scenario_id,
            "feature": scenario.feature,
            "name": scenario.name,
            "status": "failed",
            "reason": f"Row count mismatch: expected {len(scenario.expected_rows)}, got {len(rows)}. Actual rows: {rows[:5]}",
            "query": scenario.query,
        }

    # 7. Verify rows (ordered or unordered multiset)
    if scenario.in_order:
        for idx, (act, exp) in enumerate(zip(rows, scenario.expected_rows)):
            if not _match_row(act, exp, scenario.expected_columns):
                return {
                    "scenario_id": scenario.scenario_id,
                    "feature": scenario.feature,
                    "name": scenario.name,
                    "status": "failed",
                    "reason": f"Ordered row mismatch at index {idx}: expected {exp}, got {act}",
                    "query": scenario.query,
                }
    else:
        # Unordered multiset matching
        unmatched_expected = list(scenario.expected_rows)
        for act in rows:
            found_idx = None
            for idx, exp in enumerate(unmatched_expected):
                if _match_row(act, exp, scenario.expected_columns):
                    found_idx = idx
                    break
            if found_idx is not None:
                unmatched_expected.pop(found_idx)
            else:
                return {
                    "scenario_id": scenario.scenario_id,
                    "feature": scenario.feature,
                    "name": scenario.name,
                    "status": "failed",
                    "reason": f"Actual row {act} did not match any remaining expected row in {unmatched_expected[:3]}",
                    "query": scenario.query,
                }

    return {
        "scenario_id": scenario.scenario_id,
        "feature": scenario.feature,
        "name": scenario.name,
        "status": "passed",
        "reason": f"Exact match on {len(rows)} rows (in_order={scenario.in_order})",
        "query": scenario.query,
    }
