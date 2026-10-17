"""SHACL-inspired shape validator for the cricket knowledge graph.

Loads ontology/shapes.yaml once at construction. Every node and edge
insertion routes through validate_node / validate_edge, which raises
ShapeViolationError on the first failure.

Check order: required → types → enums → patterns → min/max.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "str": str,
    "int": int,
    "float": (int, float),
    "bool": bool,
    "list": list,
    "dict": dict,
}


class ShapeViolationError(ValueError):
    """Raised when a node or edge fails its shape validation."""

    def __init__(self, label: str, field: str, reason: str, value: Any = None):
        self.label = label
        self.field = field
        self.reason = reason
        self.value = value
        msg = f"[{label}.{field}] {reason}: {value!r}" if field else f"[{label}] {reason}"
        super().__init__(msg)


class ShapeValidator:
    def __init__(self, shapes_path: str | Path = "ontology/shapes.yaml") -> None:
        self.shapes_path = Path(shapes_path)
        with self.shapes_path.open() as f:
            schema = yaml.safe_load(f) or {}
        self._nodes: dict[str, dict] = schema.get("nodes") or {}
        self._edges: dict[str, dict] = schema.get("edges") or {}
        self._compiled_patterns: dict[tuple[str, str], re.Pattern[str]] = {}
        for label, shape in self._nodes.items():
            for field, pattern in (shape.get("patterns") or {}).items():
                self._compiled_patterns[(label, field)] = re.compile(pattern)

    # ── Public API ────────────────────────────────────────────────

    def validate_node(self, label: str, props: dict[str, Any]) -> None:
        shape = self._nodes.get(label)
        if shape is None:
            raise ShapeViolationError(label, "", "unknown_node_label")
        self._check_required(label, shape, props)
        self._check_types(label, shape, props)
        self._check_enums(label, shape, props)
        self._check_patterns(label, props)
        self._check_bounds(label, shape, props)

    def validate_edge(
        self,
        label: str,
        src_label: str,
        dst_label: str,
        props: dict[str, Any] | None = None,
    ) -> None:
        shape = self._edges.get(label)
        if shape is None:
            raise ShapeViolationError(label, "", "unknown_edge_label")
        expected_src = shape.get("src")
        expected_dst = shape.get("dst")
        if expected_src and src_label != expected_src:
            raise ShapeViolationError(
                label, "src", "endpoint_label", f"{src_label} != {expected_src}"
            )
        if expected_dst and dst_label != expected_dst:
            raise ShapeViolationError(
                label, "dst", "endpoint_label", f"{dst_label} != {expected_dst}"
            )
        # Property type checks (light — no required/optional split for edges).
        declared = shape.get("properties") or {}
        for key, value in (props or {}).items():
            type_name = declared.get(key)
            if type_name and not self._matches_type(value, type_name):
                raise ShapeViolationError(label, key, "type", value)

    # ── Internal checks ───────────────────────────────────────────

    @staticmethod
    def _check_required(label: str, shape: dict, props: dict) -> None:
        for field in shape.get("required") or ():
            if field not in props or props[field] is None:
                raise ShapeViolationError(label, field, "required")

    def _check_types(self, label: str, shape: dict, props: dict) -> None:
        types = shape.get("types") or {}
        for field, type_name in types.items():
            if field not in props or props[field] is None:
                continue
            if not self._matches_type(props[field], type_name):
                raise ShapeViolationError(label, field, "type", props[field])

    @staticmethod
    def _matches_type(value: Any, type_name: str) -> bool:
        expected = _TYPE_MAP.get(type_name)
        if expected is None:
            return True
        # `bool` is a subclass of `int` in Python — guard against false positives.
        if expected is int and isinstance(value, bool):
            return False
        return isinstance(value, expected)

    @staticmethod
    def _check_enums(label: str, shape: dict, props: dict) -> None:
        enums = shape.get("enums") or {}
        for field, allowed in enums.items():
            if field not in props or props[field] is None:
                continue
            if props[field] not in allowed:
                raise ShapeViolationError(label, field, "enum", props[field])

    def _check_patterns(self, label: str, props: dict) -> None:
        for (lbl, field), pattern in self._compiled_patterns.items():
            if lbl != label:
                continue
            if field not in props or props[field] is None:
                continue
            if not pattern.match(str(props[field])):
                raise ShapeViolationError(label, field, "pattern", props[field])

    @staticmethod
    def _check_bounds(label: str, shape: dict, props: dict) -> None:
        for field, lo in (shape.get("min") or {}).items():
            if field in props and props[field] is not None and props[field] < lo:
                raise ShapeViolationError(label, field, "min", props[field])
        for field, hi in (shape.get("max") or {}).items():
            if field in props and props[field] is not None and props[field] > hi:
                raise ShapeViolationError(label, field, "max", props[field])
