"""Semantic validation for GQL-Core queries.

The Lark grammar proves syntax only. This pass checks the parts of the
query that need schema knowledge: variables must be bound, known labels must
use known properties, and labelled relationships must be used with compatible
endpoint labels.

When a schema_path is provided, full schema-aware validation runs. Without
one, only structural checks (unbound variables, conflicting labels) are
performed — the engine carries no embedded domain ontology.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gql_core.query.ast import And, Comparison, Not, Or, Projection, Query, Ref
from gql_core.schema import load_shapes


class SemanticError(ValueError):
    """Raised when a syntactically valid query is not valid for the KG schema."""


@dataclass
class _Binding:
    kind: str  # "node" | "edge"
    label: str | None = None


# Module-level default schema path. Set via set_schema_path() for
# backward-compatible usage. When None, schema-aware checks are skipped.
_default_schema_path: str | Path | None = None


def set_schema_path(path: str | Path | None) -> None:
    """Set the process-wide default schema path for validate_query.

    Call once at startup; all subsequent validate_query() calls without an
    explicit schema_path argument will use this schema.
    """
    global _default_schema_path
    _default_schema_path = path


def _resolve_schema(schema_path: str | Path | None) -> dict[str, Any] | None:
    """Resolve and load a schema, or return None if no schema is available."""
    path = schema_path or _default_schema_path
    if path is None:
        return None
    raw = load_shapes(path)

    node_props: dict[str, set[str]] = {}
    node_types: dict[str, dict[str, str]] = {}
    for label, shape in (raw.get("nodes") or {}).items():
        props = set(shape.get("required") or ()) | set(shape.get("optional") or ())
        props |= set((shape.get("types") or {}).keys())
        node_props[label] = props
        node_types[label] = dict(shape.get("types") or {})

    edge_props: dict[str, set[str]] = {}
    edge_types: dict[str, dict[str, str]] = {}
    edge_shapes: dict[str, dict[str, Any]] = {}
    for label, shape in (raw.get("edges") or {}).items():
        props = set((shape.get("properties") or {}).keys())
        edge_props[label] = props
        edge_types[label] = dict(shape.get("properties") or {})
        edge_shapes[label] = dict(shape)

    return {
        "node_props": node_props,
        "node_types": node_types,
        "edge_props": edge_props,
        "edge_types": edge_types,
        "edge_shapes": edge_shapes,
    }


def validate_query(query: Query, schema_path: str | Path | None = None) -> None:
    """Validate a parsed query against the graph ontology.

    When schema_path is provided (or set via set_schema_path), full
    schema-aware checks run: known labels must use known properties, edge
    labels must exist, and endpoint labels must be compatible.

    Without a schema, only structural checks are performed (variable binding
    conflicts, unbound references). This is the generic default — the engine
    carries no embedded domain ontology.

    Unknown node labels are preserved as empty scans for backwards-compatible
    exploratory use. Unknown edge labels and property access on known labels are
    treated as errors because they almost always indicate a wrong translation.
    """
    schema = _resolve_schema(schema_path)
    bindings: dict[str, _Binding] = {}

    for pattern in query.patterns:
        for node in pattern.nodes:
            _bind_node(bindings, node.var, node.label)
            if schema is not None:
                _validate_inline_filters(schema, bindings[node.var], node.filters, node.var)

        for idx, rel in enumerate(pattern.rels):
            left = pattern.nodes[idx]
            right = pattern.nodes[idx + 1]
            if rel.label is not None and schema is not None:
                _validate_edge_label(schema, rel.label)
                _validate_endpoints(schema, rel.label, rel.direction, bindings[left.var], bindings[right.var])
            if rel.var is not None:
                _bind_edge(bindings, rel.var, rel.label)

    if query.where is not None:
        _validate_expr(schema, query.where, bindings)

    for projection in query.projections:
        _validate_projection(schema, projection, bindings)

    aliases = {_projection_key(p) for p in query.projections}
    if query.order_by is not None:
        for term in query.order_by.terms:
            if term.ref.prop is None and term.ref.var in aliases:
                continue
            _validate_ref(schema, term.ref, bindings, "ORDER BY")


def _bind_node(bindings: dict[str, _Binding], var: str, label: str | None) -> None:
    existing = bindings.get(var)
    if existing is None:
        bindings[var] = _Binding(kind="node", label=label)
        return
    if existing.kind != "node":
        raise SemanticError(f"Variable {var!r} is already bound as an edge")
    if label is not None and existing.label is not None and label != existing.label:
        raise SemanticError(
            f"Node variable {var!r} has conflicting labels {existing.label!r} and {label!r}"
        )
    if existing.label is None and label is not None:
        existing.label = label


def _bind_edge(bindings: dict[str, _Binding], var: str, label: str | None) -> None:
    existing = bindings.get(var)
    if existing is None:
        bindings[var] = _Binding(kind="edge", label=label)
        return
    if existing.kind != "edge":
        raise SemanticError(f"Variable {var!r} is already bound as a node")
    if label is not None and existing.label is not None and label != existing.label:
        raise SemanticError(
            f"Edge variable {var!r} has conflicting labels {existing.label!r} and {label!r}"
        )
    if existing.label is None and label is not None:
        existing.label = label


def _validate_inline_filters(
    schema: dict,
    binding: _Binding,
    filters: tuple[tuple[str, Any], ...],
    var: str,
) -> None:
    for prop, _value in filters:
        _validate_property(schema, binding, prop, f"inline filter on {var!r}")


def _validate_expr(schema: dict | None, expr: Any, bindings: dict[str, _Binding]) -> None:
    if isinstance(expr, Comparison):
        _validate_ref(schema, expr.lhs, bindings, "WHERE")
        return
    if isinstance(expr, (And, Or)):
        for child in expr.children:
            _validate_expr(schema, child, bindings)
        return
    if isinstance(expr, Not):
        _validate_expr(schema, expr.inner, bindings)
        return
    raise SemanticError(f"Unknown expression node {type(expr).__name__}")


def _validate_projection(schema: dict | None, projection: Projection, bindings: dict[str, _Binding]) -> None:
    _validate_ref(schema, projection.expr, bindings, "RETURN")
    if schema is None:
        return
    if projection.agg in {"SUM", "AVG"}:
        if projection.expr.prop is None:
            raise SemanticError(f"{projection.agg} requires a numeric property reference")
        type_name = _property_type(schema, bindings[projection.expr.var], projection.expr.prop)
        if type_name not in {None, "int", "float"}:
            raise SemanticError(
                f"{projection.agg} cannot be applied to non-numeric property "
                f"{projection.expr.var}.{projection.expr.prop}"
            )


def _validate_ref(schema: dict | None, ref: Ref, bindings: dict[str, _Binding], context: str) -> None:
    if ref.var == "*":
        return
    binding = bindings.get(ref.var)
    if binding is None:
        raise SemanticError(f"{context} references unbound variable {ref.var!r}")
    if ref.prop is not None and schema is not None:
        _validate_property(schema, binding, ref.prop, f"{context} reference {ref.var}.{ref.prop}")


def _validate_property(schema: dict, binding: _Binding, prop: str, context: str) -> None:
    if binding.label is None:
        return
    if binding.kind == "node":
        props = schema["node_props"].get(binding.label)
    else:
        props = schema["edge_props"].get(binding.label)
    if props is None:
        return
    if prop not in props:
        raise SemanticError(
            f"{context} uses unknown {binding.kind} property {prop!r} on label {binding.label!r}"
        )


def _property_type(schema: dict, binding: _Binding, prop: str) -> str | None:
    if binding.label is None:
        return None
    if binding.kind == "node":
        return schema["node_types"].get(binding.label, {}).get(prop)
    return schema["edge_types"].get(binding.label, {}).get(prop)


def _validate_edge_label(schema: dict, label: str) -> None:
    if label not in schema["edge_shapes"]:
        raise SemanticError(f"Unknown edge label {label!r}")


def _validate_endpoints(
    schema: dict,
    label: str,
    direction: str,
    left: _Binding,
    right: _Binding,
) -> None:
    shape = schema["edge_shapes"][label]
    src = shape.get("src")
    dst = shape.get("dst")
    if not src or not dst or left.label is None or right.label is None:
        return

    if direction == "out":
        expected = (src, dst)
    elif direction == "in":
        expected = (dst, src)
    else:
        if (left.label, right.label) in {(src, dst), (dst, src)}:
            return
        expected = (src, dst)

    if (left.label, right.label) != expected:
        raise SemanticError(
            f"Edge {label!r} with direction {direction!r} expects endpoints "
            f"{expected[0]} -> {expected[1]}, got {left.label} -> {right.label}"
        )


def _projection_key(projection: Projection) -> str:
    if projection.alias is not None:
        return projection.alias
    if projection.agg is not None:
        return f"{projection.agg.lower()}_{projection.expr.var}" + (
            f"_{projection.expr.prop}" if projection.expr.prop else ""
        )
    return projection.expr.prop or projection.expr.var
