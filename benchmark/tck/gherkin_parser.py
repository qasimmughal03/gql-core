"""Gherkin Feature File Parser for openCypher TCK.

Parses .feature files into structured Scenario objects containing:
- Background and scenario fixture statements, named graphs, procedure fixtures, and parameter tables
- Scenario Outline expansion via Examples tables
- Tested query and optional control query
- Expected result assertions (ordered/unordered rows, list-order sensitivity, empty result)
- Expected side effects (`And no side effects`, `And the side effects should be:`)
- Expected error assertions (category, compile/runtime/any-time phase, detail code)
- Unrecognized Gherkin step tracking (`parse_errors`) so unknown steps are never silently ignored
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExpectedNode:
    labels: frozenset[str]
    props: dict[str, Any]

    def __repr__(self) -> str:
        lbl_str = "".join(f":{l}" for l in sorted(self.labels))
        if self.props:
            return f"({lbl_str} {self.props})"
        return f"({lbl_str})"


@dataclass(frozen=True)
class ExpectedRel:
    rel_type: str
    props: dict[str, Any]

    def __repr__(self) -> str:
        t_str = f":{self.rel_type}" if self.rel_type else ""
        if self.props:
            return f"[{t_str} {self.props}]"
        return f"[{t_str}]"


@dataclass(frozen=True)
class ExpectedPath:
    nodes: tuple[ExpectedNode, ...]
    rels: tuple[ExpectedRel, ...]
    directions: tuple[str, ...]  # "out" (->), "in" (<-), "undirected" (--)

    def __repr__(self) -> str:
        parts: list[str] = []
        for idx, node in enumerate(self.nodes):
            parts.append(repr(node))
            if idx < len(self.rels):
                rel = self.rels[idx]
                d = self.directions[idx]
                if d == "out":
                    parts.append(f"-{rel!r}->")
                elif d == "in":
                    parts.append(f"<-{rel!r}-")
                else:
                    parts.append(f"-{rel!r}-")
        return f"<{''.join(parts)}>"


@dataclass
class TCKScenario:
    scenario_id: str
    feature: str
    name: str
    file_path: str
    is_outline: bool = False
    background_create: list[str] = field(default_factory=list)
    scenario_create: list[str] = field(default_factory=list)
    query: str = ""
    expected_kind: str = "result"  # "result", "empty", "syntax_error", "semantic_error", "type_error", "argument_error", "entity_not_found", "constraint_error", "procedure_error", "parameter_missing", "error"
    expected_error_type: str | None = None
    expected_error_phase: str | None = None  # "compile_time", "runtime", "any_time"
    expected_error_detail: str | None = None
    in_order: bool = False
    ignore_list_order: bool = False
    expected_columns: list[str] = field(default_factory=list)
    expected_rows: list[dict[str, Any]] = field(default_factory=list)
    expect_no_side_effects: bool = False
    expected_side_effects: dict[str, int] | None = None
    control_query: str = ""
    control_expected_kind: str | None = None
    control_in_order: bool = False
    control_ignore_list_order: bool = False
    control_expected_columns: list[str] = field(default_factory=list)
    control_expected_rows: list[dict[str, Any]] = field(default_factory=list)
    procedures: dict[str, dict[str, Any]] = field(default_factory=dict)
    named_graph: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    parse_errors: list[str] = field(default_factory=list)


_ALLOWED_SIDE_EFFECT_KEYS = frozenset({
    "+nodes",
    "-nodes",
    "+relationships",
    "-relationships",
    "+labels",
    "-labels",
    "+properties",
    "-properties",
})

_ERROR_TYPE_TO_KIND = {
    "SyntaxError": "syntax_error",
    "SemanticError": "semantic_error",
    "CompileTimeError": "semantic_error",
    "TypeError": "type_error",
    "ArgumentError": "argument_error",
    "EntityNotFound": "entity_not_found",
    "ConstraintVerificationFailed": "constraint_error",
    "ProcedureError": "procedure_error",
    "ParameterMissing": "parameter_missing",
}


def _split_top_level(s: str, sep: str = ",") -> list[str]:
    parts: list[str] = []
    curr: list[str] = []
    depth = 0
    angle_depth = 0
    in_quote: str | None = None
    escaped = False
    for idx, ch in enumerate(s):
        if escaped:
            curr.append(ch)
            escaped = False
            continue
        if ch == "\\":
            curr.append(ch)
            escaped = True
            continue
        if in_quote:
            curr.append(ch)
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ("'", '"'):
            in_quote = ch
            curr.append(ch)
            continue
        if ch in "([{":
            depth += 1
            curr.append(ch)
            continue
        if ch in ")]}":
            depth = max(0, depth - 1)
            curr.append(ch)
            continue
        if ch == "<" and depth == 0:
            rest = s[idx + 1 :].lstrip()
            if rest.startswith("("):
                angle_depth += 1
            curr.append(ch)
            continue
        if ch == ">" and angle_depth > 0 and depth == 0:
            prev = s[:idx].rstrip()
            if prev.endswith(")"):
                angle_depth = max(0, angle_depth - 1)
            curr.append(ch)
            continue
        if ch == sep and depth == 0 and angle_depth == 0:
            part = "".join(curr).strip()
            if part:
                parts.append(part)
            curr = []
            continue
        curr.append(ch)
    if curr:
        part = "".join(curr).strip()
        if part:
            parts.append(part)
    return parts


def _split_top_level_commas(s: str) -> list[str]:
    return _split_top_level(s, ",")


def _split_top_level_colon(s: str) -> tuple[str, str] | None:
    depth = 0
    in_quote: str | None = None
    escaped = False
    for idx, ch in enumerate(s):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if in_quote:
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ("'", '"'):
            in_quote = ch
            continue
        if ch in "([{<":
            depth += 1
            continue
        if ch in ")]}>":
            depth = max(0, depth - 1)
            continue
        if ch == ":" and depth == 0:
            return s[:idx], s[idx + 1 :]
    return None


def _unescape_gherkin_string(raw: str) -> str:
    """Unescape Gherkin table string literal content."""
    out: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i] == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt == "n":
                out.append("\n")
                i += 2
            elif nxt == "t":
                out.append("\t")
                i += 2
            elif nxt == "r":
                out.append("\r")
                i += 2
            elif nxt == "b":
                out.append("\b")
                i += 2
            elif nxt == "'":
                out.append("'")
                i += 2
            elif nxt == '"':
                out.append('"')
                i += 2
            elif nxt == "\\":
                if i + 3 < len(raw) and raw[i : i + 4] == "\\\\\\\\":
                    out.append("\\")
                    i += 4
                else:
                    out.append("\\")
                    i += 2
            else:
                out.append(raw[i])
                i += 1
        else:
            out.append(raw[i])
            i += 1
    return "".join(out)


def _parse_map_literal(s: str) -> dict[str, Any]:
    s = s.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return {}
    inner = s[1:-1].strip()
    if not inner:
        return {}
    entries: dict[str, Any] = {}
    for part in _split_top_level(inner, ","):
        colon_pair = _split_top_level_colon(part)
        if colon_pair:
            k, v = colon_pair
            entries[k.strip().strip("'\"")] = _parse_cell_value(v)
    return entries


def _parse_expected_node(s: str) -> ExpectedNode:
    s = s.strip()
    inner = s[1:-1].strip()
    props: dict[str, Any] = {}
    brace_idx = -1
    depth = 0
    in_quote: str | None = None
    escaped = False
    for idx, ch in enumerate(inner):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if in_quote:
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ("'", '"'):
            in_quote = ch
            continue
        if ch == "{":
            if depth == 0:
                brace_idx = idx
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
    if brace_idx != -1:
        label_part = inner[:brace_idx].strip()
        props_part = inner[brace_idx:].strip()
        props = _parse_map_literal(props_part)
    else:
        label_part = inner
    labels = frozenset(re.findall(r":([a-zA-Z0-9_]+)", label_part))
    return ExpectedNode(labels=labels, props=props)


def _parse_expected_rel(s: str) -> ExpectedRel:
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
    else:
        inner = s
    props: dict[str, Any] = {}
    brace_idx = -1
    depth = 0
    in_quote: str | None = None
    escaped = False
    for idx, ch in enumerate(inner):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if in_quote:
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ("'", '"'):
            in_quote = ch
            continue
        if ch == "{":
            if depth == 0:
                brace_idx = idx
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
    if brace_idx != -1:
        type_part = inner[:brace_idx].strip()
        props_part = inner[brace_idx:].strip()
        props = _parse_map_literal(props_part)
    else:
        type_part = inner
    m = re.search(r":([a-zA-Z0-9_]+)", type_part)
    rel_type = m.group(1) if m else ""
    return ExpectedRel(rel_type=rel_type, props=props)


def _parse_expected_path(s: str) -> ExpectedPath:
    s = s.strip()
    inner = s[1:-1].strip()
    nodes: list[ExpectedNode] = []
    rels: list[ExpectedRel] = []
    directions: list[str] = []

    i = 0
    n = len(inner)
    while i < n:
        while i < n and inner[i].isspace():
            i += 1
        if i >= n:
            break
        if inner[i] == "(":
            depth = 0
            in_quote: str | None = None
            escaped = False
            start = i
            while i < n:
                ch = inner[i]
                if escaped:
                    escaped = False
                    i += 1
                    continue
                if ch == "\\":
                    escaped = True
                    i += 1
                    continue
                if in_quote:
                    if ch == in_quote:
                        in_quote = None
                    i += 1
                    continue
                if ch in ("'", '"'):
                    in_quote = ch
                    i += 1
                    continue
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            nodes.append(_parse_expected_node(inner[start:i]))
        else:
            is_left = False
            if inner.startswith("<-", i):
                is_left = True
                i += 2
            elif inner.startswith("-", i):
                i += 1
            while i < n and inner[i].isspace():
                i += 1
            if i < n and inner[i] == "[":
                depth = 0
                in_quote = None
                escaped = False
                start = i
                while i < n:
                    ch = inner[i]
                    if escaped:
                        escaped = False
                        i += 1
                        continue
                    if ch == "\\":
                        escaped = True
                        i += 1
                        continue
                    if in_quote:
                        if ch == in_quote:
                            in_quote = None
                        i += 1
                        continue
                    if ch in ("'", '"'):
                        in_quote = ch
                        i += 1
                        continue
                    if ch == "[":
                        depth += 1
                    elif ch == "]":
                        depth -= 1
                        if depth == 0:
                            i += 1
                            break
                    i += 1
                rel_obj = _parse_expected_rel(inner[start:i])
            else:
                rel_obj = ExpectedRel(rel_type="", props={})
            while i < n and inner[i].isspace():
                i += 1
            is_right = False
            if inner.startswith("->", i):
                is_right = True
                i += 2
            elif inner.startswith("-", i):
                i += 1
            if is_left and not is_right:
                direction = "in"
            elif is_right and not is_left:
                direction = "out"
            else:
                direction = "undirected"
            rels.append(rel_obj)
            directions.append(direction)

    return ExpectedPath(nodes=tuple(nodes), rels=tuple(rels), directions=tuple(directions))


def _parse_cell_value(cell: str) -> Any:
    """Parse a single cell in a Gherkin result table into typed Python/TCK objects."""
    c = cell.strip()
    if c == "null":
        return None
    if c == "true":
        return True
    if c == "false":
        return False
    if c == "NaN":
        return float("nan")
    if c in ("Infinity", "Inf"):
        return float("inf")
    if c in ("-Infinity", "-Inf"):
        return float("-inf")
    if (c.startswith("'") and c.endswith("'")) or (c.startswith('"') and c.endswith('"')):
        return _unescape_gherkin_string(c[1:-1])
    if c.startswith("<") and c.endswith(">") and "(" in c and ")" in c:
        return _parse_expected_path(c)
    if c.startswith("(") and c.endswith(")"):
        return _parse_expected_node(c)
    if c.startswith("[") and c.endswith("]"):
        if c == "[]":
            return []
        if c.startswith("[:") and len(_split_top_level(c[1:-1], ",")) == 1 and not c[1:-1].strip().startswith("["):
            return _parse_expected_rel(c)
        items = [_parse_cell_value(x) for x in _split_top_level(c[1:-1], ",") if x.strip()]
        return items
    if c.startswith("{") and c.endswith("}"):
        return _parse_map_literal(c)
    try:
        return int(c)
    except ValueError:
        pass
    if "." in c or "e" in c.lower():
        try:
            return float(c)
        except ValueError:
            pass
    return c


def _extract_raw_table(lines: list[str], start_idx: int) -> tuple[list[str], list[list[str]], int]:
    idx = start_idx
    columns: list[str] = []
    raw_rows: list[list[str]] = []

    while idx < len(lines):
        line = lines[idx].strip()
        if not line or line.startswith("#"):
            idx += 1
            continue
        if not (line.startswith("|") and line.endswith("|")):
            break
        columns = [c.strip() for c in line[1:-1].split("|")]
        idx += 1
        break

    while idx < len(lines):
        line = lines[idx].strip()
        if not line or line.startswith("#"):
            if line.startswith("#"):
                idx += 1
                continue
            break
        if not (line.startswith("|") and line.endswith("|")):
            break
        cells = [c.strip() for c in line[1:-1].split("|")]
        raw_rows.append(cells)
        idx += 1

    return columns, raw_rows, idx


def _parse_table(lines: list[str], start_idx: int) -> tuple[list[str], list[dict[str, Any]], int]:
    """Parse Gherkin table: | col1 | col2 |"""
    cols, raw_rows, next_idx = _extract_raw_table(lines, start_idx)
    rows = [
        {col_name: _parse_cell_value(cell) for col_name, cell in zip(cols, r)}
        for r in raw_rows
    ]
    return cols, rows, next_idx


def _substitute_placeholders(text: str, mapping: dict[str, str]) -> str:
    if not mapping or "<" not in text:
        return text
    out = text
    for k, v in mapping.items():
        out = out.replace(f"<{k}>", v)
    return out


def _parse_scenario_steps(
    step_lines: list[str],
    base_scenario: TCKScenario,
    placeholder_map: dict[str, str] | None = None,
) -> TCKScenario:
    sc = TCKScenario(
        scenario_id=base_scenario.scenario_id,
        feature=base_scenario.feature,
        name=_substitute_placeholders(base_scenario.name, placeholder_map or {}),
        file_path=base_scenario.file_path,
        is_outline=base_scenario.is_outline,
        background_create=list(base_scenario.background_create),
        procedures=dict(base_scenario.procedures),
        named_graph=base_scenario.named_graph,
    )

    pmap = placeholder_map or {}
    in_control_query = False
    i = 0
    n = len(step_lines)

    while i < n:
        raw_line = step_lines[i]
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("@"):
            i += 1
            continue

        # 1. Graph setup
        m_g = re.match(r"^Given\s+(?:the\s+|an\s+)?([a-zA-Z0-9_\-]+)\s+graph$", stripped, re.I)
        if m_g:
            g_name = m_g.group(1).strip()
            if g_name.lower() not in ("any", "empty"):
                sc.named_graph = g_name
            i += 1
            continue

        # 2. Procedure registration
        if stripped.startswith(("And there exists a procedure", "Given there exists a procedure")):
            m_proc = re.search(r"procedure\s+([a-zA-Z0-9_\.]+)\s*\((.*?)\)\s*::\s*\((.*?)\)\s*:", stripped)
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
                cols, raw_rows, next_i = _extract_raw_table(step_lines, i + 1)
                sub_cols = [_substitute_placeholders(c, pmap) for c in cols]
                rows = [
                    {col_name: _parse_cell_value(_substitute_placeholders(cell, pmap)) for col_name, cell in zip(sub_cols, r)}
                    for r in raw_rows
                ]
                sc.procedures[p_name] = {"signature": (in_params, out_params), "rows": rows}
                i = next_i
                continue
            else:
                sc.parse_errors.append(f"Malformed procedure step: {stripped}")
                i += 1
                continue

        # 3. Parameters table
        if stripped in ("And parameters are:", "Given parameters are:"):
            idx = i + 1
            while idx < n:
                line_p = step_lines[idx].strip()
                if not line_p or line_p.startswith("#"):
                    if not line_p:
                        break
                    idx += 1
                    continue
                if not (line_p.startswith("|") and line_p.endswith("|")):
                    break
                parts = [c.strip() for c in line_p[1:-1].split("|")]
                if len(parts) >= 2:
                    k = _substitute_placeholders(parts[0], pmap).strip("'\"")
                    v = _parse_cell_value(_substitute_placeholders(parts[1], pmap))
                    sc.parameters[k] = v
                idx += 1
            i = idx
            continue

        # 4. Triple-quoted query / fixture blocks
        if stripped in (
            "And having executed:",
            "Given having executed:",
            "When executing query:",
            "When executing control query:",
            "And executing control query:",
        ):
            step_header = stripped
            i += 1
            while i < n and not step_lines[i].strip():
                i += 1
            if i < n and '"""' in step_lines[i]:
                i += 1
                block_lines: list[str] = []
                while i < n and '"""' not in step_lines[i]:
                    block_lines.append(step_lines[i])
                    i += 1
                if i < n and '"""' in step_lines[i]:
                    i += 1
                block_text = _substitute_placeholders("\n".join(block_lines).strip(), pmap)
                if "having executed:" in step_header:
                    sc.scenario_create.append(block_text)
                elif "executing control query:" in step_header:
                    sc.control_query = block_text
                    in_control_query = True
                elif "executing query:" in step_header:
                    sc.query = block_text
                    in_control_query = False
                continue
            else:
                sc.parse_errors.append(f"Expected docstring after '{step_header}'")
                continue

        # 5. Result expectations
        if stripped in ("Then the result should be empty", "Then the result should be (empty)"):
            if in_control_query:
                sc.control_expected_kind = "empty"
            else:
                sc.expected_kind = "empty"
            i += 1
            continue

        if stripped.startswith("Then the result should be"):
            if stripped not in (
                "Then the result should be, in any order:",
                "Then the result should be, in order:",
                "Then the result should be (ignoring element order for lists):",
                "Then the result should be, in any order (ignoring element order for lists):",
                "Then the result should be, in order (ignoring element order for lists):",
            ):
                sc.parse_errors.append(f"Unrecognized result assertion modifier: {stripped}")
                i += 1
                continue
            in_ord = ("in order" in stripped and "any order" not in stripped)
            ign_list = "ignoring element order for lists" in stripped
            cols, raw_rows, next_i = _extract_raw_table(step_lines, i + 1)
            sub_cols = [_substitute_placeholders(c, pmap) for c in cols]
            rows = [
                {col_name: _parse_cell_value(_substitute_placeholders(cell, pmap)) for col_name, cell in zip(sub_cols, r)}
                for r in raw_rows
            ]
            if in_control_query:
                sc.control_expected_kind = "result"
                sc.control_in_order = in_ord
                sc.control_ignore_list_order = ign_list
                sc.control_expected_columns = sub_cols
                sc.control_expected_rows = rows
            else:
                sc.expected_kind = "result"
                sc.in_order = in_ord
                sc.ignore_list_order = ign_list
                sc.expected_columns = sub_cols
                sc.expected_rows = rows
            i = next_i
            continue

        # 6. Side effects
        if stripped == "And no side effects":
            sc.expect_no_side_effects = True
            sc.expected_side_effects = {}
            i += 1
            continue

        if stripped == "And the side effects should be:":
            idx = i + 1
            se_dict: dict[str, int] = {}
            while idx < n:
                line_se = step_lines[idx].strip()
                if not line_se or line_se.startswith("#"):
                    if not line_se:
                        break
                    idx += 1
                    continue
                if not (line_se.startswith("|") and line_se.endswith("|")):
                    break
                parts = [c.strip() for c in line_se[1:-1].split("|")]
                if len(parts) >= 2:
                    se_key = _substitute_placeholders(parts[0], pmap)
                    se_val_str = _substitute_placeholders(parts[1], pmap)
                    if se_key not in _ALLOWED_SIDE_EFFECT_KEYS:
                        sc.parse_errors.append(f"Unknown side-effect key: {se_key}")
                    try:
                        se_val = int(se_val_str)
                        if se_val != 0:
                            se_dict[se_key] = se_val
                    except ValueError:
                        sc.parse_errors.append(f"Invalid side-effect count for {se_key}: {se_val_str}")
                idx += 1
            sc.expected_side_effects = se_dict
            sc.expect_no_side_effects = (len(se_dict) == 0)
            i = idx
            continue

        # 7. Error expectations
        m_err = re.match(
            r"^Then\s+an?\s+([A-Za-z0-9_]+)\s+should\s+be\s+raised\s+at\s+(compile time|runtime|any time)\s*:\s*(.+)$",
            stripped,
        )
        if m_err:
            err_type = m_err.group(1).strip()
            err_phase_raw = m_err.group(2).strip()
            err_detail = m_err.group(3).strip()
            phase_map = {
                "compile time": "compile_time",
                "runtime": "runtime",
                "any time": "any_time",
            }
            sc.expected_error_type = err_type
            sc.expected_error_phase = phase_map[err_phase_raw]
            sc.expected_error_detail = err_detail
            sc.expected_kind = _ERROR_TYPE_TO_KIND.get(err_type, "error")
            if err_type not in _ERROR_TYPE_TO_KIND:
                sc.parse_errors.append(f"Unknown expected error type: {err_type}")
            i += 1
            continue

        # 8. Unrecognized step — never silently ignore!
        sc.parse_errors.append(f"Unrecognized Gherkin step: {stripped}")
        i += 1

    return sc


def parse_feature_file(path: Path | str, expand_outlines: bool = True) -> list[TCKScenario]:
    """Parse all scenarios (including Scenario Outline expansions) in an openCypher TCK feature file."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    feature_name = path.stem
    background_create: list[str] = []
    background_procedures: dict[str, dict[str, Any]] = {}
    background_graph: str = ""
    background_errors: list[str] = []
    scenarios: list[TCKScenario] = []

    i = 0
    n = len(lines)
    in_background = False

    blocks: list[tuple[bool, str, int, list[str]]] = []
    bg_lines: list[str] = []
    scenario_idx = 0

    while i < n:
        stripped = lines[i].strip()
        if stripped.startswith("#") or stripped.startswith("@"):
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
        if stripped.startswith("Scenario Outline:") or stripped.startswith("Scenario:"):
            in_background = False
            is_outline = stripped.startswith("Scenario Outline:")
            raw_title = stripped.split(":", 1)[1].strip()
            scenario_idx += 1
            i += 1
            block_start = i
            in_doc = False
            while i < n:
                s_inner = lines[i].strip()
                if '"""' in s_inner:
                    in_doc = not in_doc
                elif not in_doc and (s_inner.startswith("Scenario:") or s_inner.startswith("Scenario Outline:")):
                    break
                i += 1
            blocks.append((is_outline, raw_title, scenario_idx, lines[block_start:i]))
            continue
        if in_background:
            bg_lines.append(lines[i])
        i += 1

    if bg_lines:
        bg_dummy = TCKScenario(
            scenario_id="bg",
            feature=feature_name,
            name="Background",
            file_path=str(path),
        )
        bg_parsed = _parse_scenario_steps(bg_lines, bg_dummy)
        background_create = bg_parsed.scenario_create
        background_procedures = bg_parsed.procedures
        background_graph = bg_parsed.named_graph
        background_errors = bg_parsed.parse_errors

    for is_outline, raw_title, sc_idx, b_lines in blocks:
        m_id = re.match(r"^\[(.*?)\]\s*(.*)$", raw_title)
        if m_id:
            s_id = m_id.group(1)
            s_name = m_id.group(2)
        else:
            s_id = str(sc_idx)
            s_name = raw_title

        base_sc = TCKScenario(
            scenario_id=f"{path.stem}#{s_id}",
            feature=feature_name,
            name=s_name,
            file_path=str(path),
            is_outline=is_outline,
            background_create=list(background_create),
            procedures=dict(background_procedures),
            named_graph=background_graph,
        )

        if not is_outline:
            sc = _parse_scenario_steps(b_lines, base_sc)
            if background_errors:
                sc.parse_errors = list(background_errors) + sc.parse_errors
            scenarios.append(sc)
        elif expand_outlines:
            ex_idx = -1
            in_doc = False
            for idx_b, bl in enumerate(b_lines):
                s_bl = bl.strip()
                if '"""' in s_bl:
                    in_doc = not in_doc
                elif not in_doc and s_bl.startswith("Examples:"):
                    ex_idx = idx_b
                    break
            if ex_idx == -1:
                base_sc.parse_errors.append("Scenario Outline missing Examples: table")
                scenarios.append(base_sc)
            else:
                step_part = b_lines[:ex_idx]
                ex_cols, ex_rows, _ = _extract_raw_table(b_lines, ex_idx + 1)
                for row_num, ex_row in enumerate(ex_rows, start=1):
                    pmap = dict(zip(ex_cols, ex_row))
                    row_base = TCKScenario(
                        scenario_id=f"{path.stem}#{s_id}#{row_num}",
                        feature=feature_name,
                        name=s_name,
                        file_path=str(path),
                        is_outline=True,
                        background_create=list(background_create),
                        procedures=dict(background_procedures),
                        named_graph=background_graph,
                    )
                    sc = _parse_scenario_steps(step_part, row_base, placeholder_map=pmap)
                    if background_errors:
                        sc.parse_errors = list(background_errors) + sc.parse_errors
                    scenarios.append(sc)

    return scenarios
