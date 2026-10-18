"""Operator Registry and LLM-facing Schema Description Generator for GQL-Core.

Exposes metadata for all logical and physical operators:
- Operator name, category, input/output types, argument schema, semantics, nesting, examples.
- Generates prompt-ready LLM descriptions of available entities, relationships, and operators.
- Validates and executes structured plans independently of any LLM or remote network call.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from gql_core.graph import PropertyGraph
from gql_core.ir import RelOp, plan_from_dict
from gql_core.ontology.schema import OntologySchema
from gql_core.physical.engine import execute_physical_plan, explain_plan
from gql_core.validator_ir import ValidationReport, validate_logical_plan


@dataclass(frozen=True)
class OperatorMetadata:
    name: str
    category: str  # "Relational", "Boolean", "Scalar", "Quantifier", "Temporal", "Aggregate"
    input_types: list[str]
    output_type: str
    argument_schema: dict[str, str]
    semantics: str
    cost_characteristic: str
    example_json: dict[str, Any]


_OPERATOR_REGISTRY: dict[str, OperatorMetadata] = {
    "Scan": OperatorMetadata(
        name="Scan",
        category="Relational",
        input_types=["Graph"],
        output_type="Relation",
        argument_schema={"var": "str", "label": "str | None", "inline_filters": "list[tuple[str, Any]]"},
        semantics="Scans nodes by label or all nodes, binding each to var.",
        cost_characteristic="O(N) where N is label node count; indexed in PropertyGraph.",
        example_json={"_type": "Scan", "var": "p", "label": "Person", "inline_filters": []},
    ),
    "Expand": OperatorMetadata(
        name="Expand",
        category="Relational",
        input_types=["Relation", "Graph"],
        output_type="Relation",
        argument_schema={
            "from_var": "str",
            "edge_label": "str | None",
            "direction": "'out' | 'in' | 'undirected'",
            "to_var": "str",
            "to_label": "str | None",
            "optional": "bool",
        },
        semantics="Traverses relationships incident to from_var, binding to_var. Supports OPTIONAL MATCH.",
        cost_characteristic="O(D) where D is out-degree of from_var.",
        example_json={
            "_type": "Expand",
            "from_var": "p",
            "edge_label": "KNOWS",
            "direction": "out",
            "to_var": "friend",
            "to_label": "Person",
            "optional": False,
        },
    ),
    "RecursiveExpand": OperatorMetadata(
        name="RecursiveExpand",
        category="Relational",
        input_types=["Relation", "Graph"],
        output_type="Relation",
        argument_schema={
            "from_var": "str",
            "edge_label": "str | None",
            "direction": "str",
            "min_hops": "int",
            "max_hops": "int | None",
            "to_var": "str",
            "trail_semantics": "bool",
        },
        semantics="Bounded hop RPQ traversal enforcing openCypher relationship trail semantics (no repeated edges).",
        cost_characteristic="O(D^k) where D is branching factor and k is hop count.",
        example_json={
            "_type": "RecursiveExpand",
            "from_var": "a",
            "edge_label": "NEXT",
            "direction": "out",
            "min_hops": 1,
            "max_hops": 3,
            "to_var": "b",
            "trail_semantics": True,
        },
    ),
    "Filter": OperatorMetadata(
        name="Filter",
        category="Relational",
        input_types=["Relation"],
        output_type="Relation",
        argument_schema={"predicate": "BoolExpr"},
        semantics="Filters rows retaining strictly rows where predicate evaluates to True under 3VL Kleene logic.",
        cost_characteristic="O(R) where R is row count.",
        example_json={"_type": "Filter", "predicate": {"_type": "Comparison", "op": ">", "lhs": {"_type": "Property", "var": "p", "prop": "age"}, "rhs": {"_type": "Literal", "value": 21}}},
    ),
    "Project": OperatorMetadata(
        name="Project",
        category="Relational",
        input_types=["Relation"],
        output_type="Relation",
        argument_schema={"projections": "list[{expr: ValueExpr, alias: str}]", "distinct": "bool"},
        semantics="Projects computed expressions into named aliases, dropping unprojected bindings.",
        cost_characteristic="O(R * P) where P is projection count.",
        example_json={"_type": "Project", "projections": [{"expr": {"_type": "Property", "var": "p", "prop": "name"}, "alias": "name"}], "distinct": False},
    ),
    "Join": OperatorMetadata(
        name="Join",
        category="Relational",
        input_types=["Relation", "Relation"],
        output_type="Relation",
        argument_schema={"on": "list[str]", "kind": "'INNER' | 'LEFT_OUTER' | 'SEMI' | 'ANTI' | 'CROSS'"},
        semantics="Performs hash-join or outer/semi/anti join between left and right relations on shared variables.",
        cost_characteristic="O(|L| + |R|) for hash join; O(|L| * |R|) for cross join.",
        example_json={"_type": "Join", "on": ["user_id"], "kind": "INNER"},
    ),
    "Union": OperatorMetadata(
        name="Union",
        category="Relational",
        input_types=["Relation", "Relation"],
        output_type="Relation",
        argument_schema={"all": "bool"},
        semantics="Computes set union (all=False) or multiset bag union (all=True).",
        cost_characteristic="O(|L| + |R|).",
        example_json={"_type": "Union", "all": True},
    ),
    "Intersect": OperatorMetadata(
        name="Intersect",
        category="Relational",
        input_types=["Relation", "Relation"],
        output_type="Relation",
        argument_schema={"all": "bool"},
        semantics="Computes set intersection or multiset intersection.",
        cost_characteristic="O(|L| + |R|).",
        example_json={"_type": "Intersect", "all": False},
    ),
    "Except": OperatorMetadata(
        name="Except",
        category="Relational",
        input_types=["Relation", "Relation"],
        output_type="Relation",
        argument_schema={"all": "bool"},
        semantics="Computes set difference or multiset difference.",
        cost_characteristic="O(|L| + |R|).",
        example_json={"_type": "Except", "all": False},
    ),
    "GroupBy": OperatorMetadata(
        name="GroupBy",
        category="Relational",
        input_types=["Relation"],
        output_type="Relation",
        argument_schema={"keys": "list[str]", "aggregates": "list[{expr: AggregateExpr, alias: str}]"},
        semantics="Partitions rows by multi-keys and evaluates aggregate expressions (COUNT, SUM, AVG, MIN, MAX, COLLECT).",
        cost_characteristic="O(R) hash partitioning.",
        example_json={"_type": "GroupBy", "keys": ["dept"], "aggregates": [{"expr": {"_type": "AggregateExpr", "func": "COUNT", "expr": None}, "alias": "cnt"}]},
    ),
    "Exists": OperatorMetadata(
        name="Exists",
        category="Boolean",
        input_types=["PatternExpr | RelOp"],
        output_type="BOOLEAN",
        argument_schema={"subquery_or_pattern": "PatternExpr | RelOp"},
        semantics="Early-terminating existence probe over correlated graph pattern or subquery.",
        cost_characteristic="O(1) to O(D) with early termination on first match.",
        example_json={"_type": "Exists", "target": {"_type": "PatternExpr", "source_var": "p", "rel_label": "HAS_SKILL", "direction": "out", "target_var": "s"}},
    ),
    "QuantifiedRel": OperatorMetadata(
        name="QuantifiedRel",
        category="Quantifier",
        input_types=["GraphEntity"],
        output_type="BOOLEAN",
        argument_schema={
            "quantifier": "'ANY' | 'ALL' | 'NONE' | 'SINGLE' | 'AT_LEAST' | 'AT_MOST' | 'EXACTLY'",
            "source_var": "str",
            "rel_label": "str",
            "count": "int | None",
            "predicate": "BoolExpr | None",
        },
        semantics="Evaluates relationship quantification with vacuous truth for ALL on empty set and distinct entity counting.",
        cost_characteristic="O(D) where D is incident relationships.",
        example_json={"_type": "QuantifiedRel", "quantifier": "AT_LEAST", "source_var": "p", "rel_label": "PLACED", "direction": "out", "target_var": "o", "count": 3},
    ),
}


class OperatorRegistry:
    """Registry providing operator inspection, validation, and LLM prompt generation."""

    @classmethod
    def list_operators(cls) -> list[str]:
        return sorted(_OPERATOR_REGISTRY.keys())

    @classmethod
    def get_operator(cls, name: str) -> OperatorMetadata | None:
        return _OPERATOR_REGISTRY.get(name)

    @classmethod
    def generate_llm_prompt(cls, schema: OntologySchema | None = None) -> str:
        """Generate a complete, structured prompt describing the query DSL for an LLM."""
        lines = [
            "# GQL-Core Typed Query Language Specification for LLM Generation",
            "",
            "Generate JSON query plans conforming to the GQL-Core canonical IR format.",
            "Do NOT output natural language or markdown code blocks when requesting a plan.",
            "Output a JSON object starting with `{\"version\": \"1.0\", \"_type\": ...}`.",
            "",
            "## Available Operators",
        ]
        for name, meta in sorted(_OPERATOR_REGISTRY.items()):
            lines.append(f"### `{meta.name}` ({meta.category})")
            lines.append(f"- **Description**: {meta.semantics}")
            lines.append(f"- **Arguments**: `{json.dumps(meta.argument_schema)}`")
            lines.append(f"- **Example**: `{json.dumps(meta.example_json)}`")
            lines.append("")

        if schema:
            lines.append("## Available Ontology Schema")
            lines.append("### Entities")
            for ent_name, ent in sorted(schema.entities.items()):
                props = ", ".join(f"{p}: {d.type.value}" for p, d in ent.properties.items())
                supertypes = f" (extends {', '.join(ent.supertypes)})" if ent.supertypes else ""
                lines.append(f"- **{ent_name}**{supertypes}: {props}")

            lines.append("\n### Relationships")
            for rel_name, rel in sorted(schema.relationships.items()):
                inv = f", inverse={rel.inverse}" if rel.inverse else ""
                sym = ", symmetric" if rel.is_symmetric else ""
                trans = ", transitive" if rel.is_transitive else ""
                lines.append(f"- **{rel.source_type}** -[:{rel_name}{inv}{sym}{trans}]-> **{rel.target_type}**")

        return "\n".join(lines)


def execute_plan(
    plan: RelOp | dict[str, Any] | str,
    graph: PropertyGraph,
    schema: OntologySchema | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    """Public execution entry point for validated structured plans.

    Accepts:
    - RelOp AST instance
    - JSON dictionary
    - JSON string

    Returns:
    - {"status": "SUCCESS", "rows": [...], "count": int, "explanation": str}
    or raises PlanValidationError on failure.
    """
    if isinstance(plan, str):
        plan_dict = json.loads(plan)
        root_op = plan_from_dict(plan_dict)
    elif isinstance(plan, dict):
        root_op = plan_from_dict(plan)
    elif isinstance(plan, RelOp):
        root_op = plan
    else:
        raise TypeError(f"Unsupported plan input type: {type(plan).__name__}")

    # Validate plan
    report = validate_logical_plan(root_op, strict=strict)
    if not report.is_valid:
        raise report.errors[0]

    # Execute
    rows = execute_physical_plan(root_op, graph)
    return {
        "status": "SUCCESS",
        "rows": rows,
        "count": len(rows),
        "explanation": explain_plan(root_op),
    }
