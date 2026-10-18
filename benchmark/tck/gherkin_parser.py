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
        items = [x.strip().strip("'\"") for x in c[1:-1].split(",") if x.strip()]
        return items
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
    scenarios: list[TCKScenario] = []

    i = 0
    in_background = False
    current_scenario: TCKScenario | None = None
    scenario_idx = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("Feature:"):
            feature_name = stripped.split("Feature:", 1)[1].strip()
            i += 1
            continue

        if stripped.startswith("Background:"):
            in_background = True
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
            )
            scenarios.append(current_scenario)
            i += 1
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

            if "having executed:" in prev_line or "executing query:" in prev_line:
                if "having executed:" in prev_line:
                    if in_background:
                        background_create.append(block_text)
                    elif current_scenario:
                        current_scenario.scenario_create.append(block_text)
                elif "executing query:" in prev_line and current_scenario:
                    current_scenario.query = block_text
            i += 1
            continue

        # Check for expectations
        if current_scenario:
            if "Then the result should be (empty)" in stripped or "Then the result should be empty" in stripped:
                current_scenario.expected_kind = "empty"
            elif "Then the result should be, in order:" in stripped:
                current_scenario.expected_kind = "result"
                current_scenario.in_order = True
                # Parse table
                cols, rows, next_i = _parse_table(lines, i + 1)
                current_scenario.expected_columns = cols
                current_scenario.expected_rows = rows
                i = next_i
                continue
            elif "Then the result should be, in any order:" in stripped or "Then the result should be:" in stripped:
                current_scenario.expected_kind = "result"
                current_scenario.in_order = False
                cols, rows, next_i = _parse_table(lines, i + 1)
                current_scenario.expected_columns = cols
                current_scenario.expected_rows = rows
                i = next_i
                continue
            elif "SyntaxError should be raised" in stripped:
                current_scenario.expected_kind = "syntax_error"
            elif "SemanticError should be raised" in stripped or "CompileTimeError" in stripped:
                current_scenario.expected_kind = "semantic_error"

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
