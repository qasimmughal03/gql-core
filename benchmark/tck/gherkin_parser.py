"""Gherkin Feature File Parser for openCypher TCK.

Parses .feature files into structured Scenario objects containing:
- fixture CREATE statements
- tested query
- expected result type (tabular rows, empty, SyntaxError, SemanticError)
- expected row dictionary list
- ordering requirements
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TCKScenario:
    scenario_id: str
    feature: str
    name: str
    file_path: str
    background_create: list[str] = field(default_factory=list)
    scenario_create: list[str] = field(default_factory=list)
    query: str = ""
    expected_kind: str = "result"  # "result", "empty", "syntax_error", "semantic_error"
    in_order: bool = False
    expected_columns: list[str] = field(default_factory=list)
    expected_rows: list[dict[str, Any]] = field(default_factory=list)
    control_query: str = ""
    procedures: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    named_graph: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)


def _parse_cell_value(cell: str) -> Any:
    """Parse a single cell in a Gherkin result table."""
    c = cell.strip()
    if c == "null":
        return None
    if c == "true":
        return True
    if c == "false":
        return False
    if (c.startswith("'") and c.endswith("'")) or (c.startswith('"') and c.endswith('"')):
        return c[1:-1].replace("\\'", "'").replace('\\"', '"')
    if c.startswith("[") and c.endswith("]"):
        if c == "[]":
            return []
        items = [_parse_cell_value(x) for x in c[1:-1].split(",") if x.strip()]
        return items
    if c.startswith("{") and c.endswith("}"):
        if c == "{}":
            return {}
        entries = {}
        for part in c[1:-1].split(","):
            if ":" in part:
                k, v = part.split(":", 1)
                entries[k.strip().strip("'\"")] = _parse_cell_value(v)
        return entries
    if "." in c:
        try:
            return float(c)
        except ValueError:
            pass
    try:
        return int(c)
    except ValueError:
        pass
    return c


def parse_feature_file(path: Path | str) -> list[TCKScenario]:
    """Parse all scenarios in an openCypher TCK feature file."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    feature_name = path.stem
    background_create: list[str] = []
    background_procedures: dict[str, list[dict[str, Any]]] = {}
    background_graph: str = ""
    scenarios: list[TCKScenario] = []

    i = 0
    in_background = False
    current_scenario: TCKScenario | None = None
    scenario_idx = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("#"):
            i += 1
            continue

        if stripped.startswith("Feature:"):
            feature_name = stripped.split("Feature:", 1)[1].strip()
            i += 1
            continue

        if stripped.startswith("Background:"):
            in_background = True
            i += 1
            continue

        if stripped.startswith("Scenario Outline:"):
            in_background = False
            current_scenario = None
            i += 1
            continue

        if stripped.startswith("Scenario:"):
            in_background = False
            scenario_idx += 1
            raw_title = stripped.split("Scenario:", 1)[1].strip()
            # Extract [1] scenario ID if present
            m_id = re.match(r"^\[(.*?)\]\s*(.*)$", raw_title)
            if m_id:
                s_id = m_id.group(1)
                s_name = m_id.group(2)
            else:
                s_id = str(scenario_idx)
                s_name = raw_title

            current_scenario = TCKScenario(
                scenario_id=f"{path.stem}#{s_id}",
                feature=feature_name,
                name=s_name,
                file_path=str(path),
                background_create=list(background_create),
                procedures=dict(background_procedures),
                named_graph=background_graph,
            )
            scenarios.append(current_scenario)
            i += 1
            continue

        if "graph" in stripped:
            m_g = re.search(r"Given\s+(?:the\s+)?([a-zA-Z0-9_\-]+)\s+graph", stripped, re.I)
            if m_g:
                g_name = m_g.group(1).strip()
                if g_name.lower() != "any":
                    if in_background:
                        background_graph = g_name
                    elif current_scenario:
                        current_scenario.named_graph = g_name
                i += 1
                continue

        if "there exists a procedure" in stripped:
            m_proc = re.search(r"procedure\s+([a-zA-Z0-9_\.]+)\s*\((.*?)\)\s*::\s*\((.*?)\)", stripped)
            if m_proc:
                p_name = m_proc.group(1)
                in_s = m_proc.group(2).strip()
                out_s = m_proc.group(3).strip()
                in_params = []
                for p in in_s.split(","):
                    p = p.strip()
                    if p:
                        parts = p.split("::")
                        in_params.append((parts[0].strip(), parts[1].strip() if len(parts) > 1 else "ANY"))
                out_params = [p.split("::")[0].strip() for p in out_s.split(",") if p.strip()]
                cols, rows, next_i = _parse_table(lines, i + 1)
                entry = {"signature": (in_params, out_params), "rows": rows}
                if in_background:
                    background_procedures[p_name] = entry
                elif current_scenario:
                    current_scenario.procedures[p_name] = entry
                i = next_i
                continue
            else:
                m_proc_simple = re.search(r"procedure\s+([a-zA-Z0-9_\.]+)\s*\(", stripped)
                if m_proc_simple:
                    p_name = m_proc_simple.group(1)
                    cols, rows, next_i = _parse_table(lines, i + 1)
                    entry = {"signature": ([], cols), "rows": rows}
                    if in_background:
                        background_procedures[p_name] = entry
                    elif current_scenario:
                        current_scenario.procedures[p_name] = entry
                    i = next_i
                    continue

        if "parameters are:" in stripped:
            idx = i + 1
            params = {}
            while idx < len(lines):
                line_p = lines[idx].strip()
                if not line_p:
                    idx += 1
                    continue
                if not line_p.startswith("|") or not line_p.endswith("|"):
                    break
                parts = [c.strip() for c in line_p[1:-1].split("|")]
                if len(parts) >= 2:
                    k = parts[0].strip("'\"")
                    v = _parse_cell_value(parts[1])
                    params[k] = v
                idx += 1
            if current_scenario:
                current_scenario.parameters.update(params)
            i = idx
            continue

        # Check for triple-quote block
        if '"""' in stripped:
            # Capture multi-line block
            block_lines: list[str] = []
            i += 1
            while i < len(lines) and '"""' not in lines[i]:
                block_lines.append(lines[i])
                i += 1
            block_text = "\n".join(block_lines).strip()
            prev_line = lines[i - len(block_lines) - 2].strip() if (i - len(block_lines) - 2) >= 0 else ""

            if "having executed:" in prev_line or "executing query:" in prev_line or "executing control query:" in prev_line:
                if "having executed:" in prev_line:
                    if in_background:
                        background_create.append(block_text)
                    elif current_scenario:
                        current_scenario.scenario_create.append(block_text)
                elif "executing control query:" in prev_line and current_scenario:
                    current_scenario.control_query = block_text
                elif "executing query:" in prev_line and current_scenario:
                    current_scenario.query = block_text
            i += 1
            continue

        # Check for expectations
        if current_scenario:
            if "Then the result should be (empty)" in stripped or "Then the result should be empty" in stripped:
                current_scenario.expected_kind = "empty"
            elif stripped.startswith("Then the result should be"):
                current_scenario.expected_kind = "result"
                current_scenario.in_order = ("in order:" in stripped and "any order" not in stripped)
                cols, rows, next_i = _parse_table(lines, i + 1)
                current_scenario.expected_columns = cols
                current_scenario.expected_rows = rows
                i = next_i
                continue
            elif "should be raised" in stripped:
                if "SyntaxError" in stripped:
                    current_scenario.expected_kind = "syntax_error"
                elif "SemanticError" in stripped or "CompileTimeError" in stripped:
                    current_scenario.expected_kind = "semantic_error"
                elif "TypeError" in stripped:
                    current_scenario.expected_kind = "type_error"
                elif "ConstraintVerificationFailed" in stripped:
                    current_scenario.expected_kind = "constraint_error"
                else:
                    current_scenario.expected_kind = "error"

        i += 1

    return scenarios


def _parse_table(lines: list[str], start_idx: int) -> tuple[list[str], list[dict[str, Any]], int]:
    """Parse Gherkin table: | col1 | col2 |"""
    idx = start_idx
    columns: list[str] = []
    rows: list[dict[str, Any]] = []

    # First table line is columns
    while idx < len(lines):
        line = lines[idx].strip()
        if not line or not line.startswith("|") or not line.endswith("|"):
            idx += 1
            continue
        # Extract headers
        columns = [c.strip() for c in line[1:-1].split("|")]
        idx += 1
        break

    # Subsequent table lines are rows
    while idx < len(lines):
        line = lines[idx].strip()
        if not line.startswith("|") or not line.endswith("|"):
            break
        cells = [c.strip() for c in line[1:-1].split("|")]
        row = {}
        for col_name, cell in zip(columns, cells):
            row[col_name] = _parse_cell_value(cell)
        rows.append(row)
        idx += 1

    return columns, rows, idx
