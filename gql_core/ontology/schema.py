"""Ontology Schema loader and graph structural constraint validator.

Supports loading from extended YAML shapes and validating:
- Subtype hierarchies (is_subtype_of)
- Endpoint types and allowed labels
- Cardinality constraints (min/max outgoing and incoming)
- Irreflexivity (prevent self-loops when required)
- Disjoint relationships
- ReasoningMode (CWA / OWA) lookup
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from gql_core.ontology.model import (
    CardinalityConstraint,
    EntityType,
    PropertyDef,
    ReasoningMode,
    RelationshipType,
)
from gql_core.types import DataType


class OntologyViolationError(ValueError):
    """Raised when an ontology or cardinality constraint is violated."""

    def __init__(self, code: str, message: str, entity: str = ""):
        self.code = code
        self.message = message
        self.entity = entity
        prefix = f"[{entity}] " if entity else ""
        super().__init__(f"{prefix}{code}: {message}")


class OntologySchema:
    def __init__(self) -> None:
        self.entities: dict[str, EntityType] = {}
        self.relationships: dict[str, RelationshipType] = {}
        self._ancestor_cache: dict[str, set[str]] = {}

    @classmethod
    def from_yaml(cls, path_or_stream: str | Path) -> OntologySchema:
        """Load schema from a YAML file or string."""
        if isinstance(path_or_stream, (str, Path)) and Path(path_or_stream).is_file():
            with open(path_or_stream, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        else:
            data = yaml.safe_load(str(path_or_stream)) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OntologySchema:
        schema = cls()
        nodes_data = data.get("nodes") or data.get("entities") or {}
        for name, edata in nodes_data.items():
            schema.add_entity(cls._parse_entity(name, edata))

        rels_data = data.get("edges") or data.get("relationships") or {}
        for name, rdata in rels_data.items():
            schema.add_relationship(cls._parse_relationship(name, rdata))

        schema._compute_hierarchies()
        return schema

    @staticmethod
    def _parse_entity(name: str, d: dict[str, Any]) -> EntityType:
        props: dict[str, PropertyDef] = {}
        types_map = d.get("types") or {}
        required_list = set(d.get("required") or ())
        patterns = d.get("patterns") or {}
        enums = d.get("enums") or {}
        mins = d.get("min") or {}
        maxs = d.get("max") or {}

        all_prop_names = set(types_map.keys()) | set(required_list) | set(d.get("optional") or ())
        for p in all_prop_names:
            t_str = types_map.get(p, "str").upper()
            dt = DataType(t_str) if t_str in DataType.__members__ else DataType.STRING
            props[p] = PropertyDef(
                name=p,
                type=dt,
                required=(p in required_list),
                pattern=patterns.get(p),
                enum_values=tuple(enums[p]) if p in enums else None,
                min_value=mins.get(p),
                max_value=maxs.get(p),
            )

        supertypes = tuple(d.get("subClassOf") or d.get("extends") or d.get("supertypes") or ())
        if isinstance(supertypes, str):
            supertypes = (supertypes,)

        return EntityType(
            name=name,
            properties=props,
            supertypes=tuple(supertypes),
            is_abstract=d.get("abstract", False),
            identity_prop=d.get("identity", "id"),
        )

    @staticmethod
    def _parse_relationship(name: str, d: dict[str, Any]) -> RelationshipType:
        src = d.get("src") or d.get("source") or "Node"
        dst = d.get("dst") or d.get("target") or "Node"
        card_d = d.get("cardinality") or {}
        out_card = card_d.get("outgoing") or {}
        in_card = card_d.get("incoming") or {}

        card = CardinalityConstraint(
            min_outgoing=out_card.get("min"),
            max_outgoing=out_card.get("max"),
            min_incoming=in_card.get("min"),
            max_incoming=in_card.get("max"),
        )

        mode_str = (d.get("reasoning_mode") or "CWA").upper()
        mode = ReasoningMode.OWA if mode_str == "OWA" else ReasoningMode.CWA

        return RelationshipType(
            name=name,
            source_type=src,
            target_type=dst,
            directed=d.get("directed", True),
            cardinality=card,
            inverse=d.get("inverse"),
            is_symmetric=d.get("symmetric", False),
            is_transitive=d.get("transitive", False),
            is_reflexive=d.get("reflexive", False),
            is_irreflexive=d.get("irreflexive", True),
            is_asymmetric=d.get("asymmetric", False),
            disjoint_with=tuple(d.get("disjoint_with") or ()),
            reasoning_mode=mode,
        )

    def add_entity(self, entity: EntityType) -> None:
        self.entities[entity.name] = entity
        self._ancestor_cache.clear()

    def add_relationship(self, rel: RelationshipType) -> None:
        self.relationships[rel.name] = rel

    def _compute_hierarchies(self) -> None:
        self._ancestor_cache.clear()
        for name, ent in self.entities.items():
            ancestors = set()
            stack = list(ent.supertypes)
            while stack:
                curr = stack.pop()
                if curr not in ancestors:
                    ancestors.add(curr)
                    parent = self.entities.get(curr)
                    if parent:
                        stack.extend(parent.supertypes)
            self._ancestor_cache[name] = ancestors

    def is_subtype_of(self, child: str, parent: str) -> bool:
        """Returns True if child equals parent or is a subtype of parent."""
        if child == parent:
            return True
        if child not in self._ancestor_cache:
            self._compute_hierarchies()
        return parent in self._ancestor_cache.get(child, set())

    def get_reasoning_mode(self, rel_type: str | None) -> ReasoningMode:
        if rel_type and rel_type in self.relationships:
            return self.relationships[rel_type].reasoning_mode
        return ReasoningMode.CWA

    def validate_graph(self, graph: Any) -> list[OntologyViolationError]:
        """Validate all nodes, edges, and cardinality constraints in graph."""
        violations: list[OntologyViolationError] = []

        # 1. Validate nodes
        for node in graph._nodes.values():
            if node.label and node.label in self.entities:
                ent_def = self.entities[node.label]
                for prop_name, pdef in ent_def.properties.items():
                    val = node.props.get(prop_name)
                    if pdef.required and (val is None or val == ""):
                        violations.append(
                            OntologyViolationError("REQUIRED_PROP_MISSING", f"Missing required property {prop_name}", str(node.id))
                        )
                    if val is not None:
                        if pdef.enum_values and val not in pdef.enum_values:
                            violations.append(
                                OntologyViolationError("ENUM_VIOLATION", f"Property {prop_name} value {val!r} not in {pdef.enum_values}", str(node.id))
                            )
                        if pdef.pattern and isinstance(val, str) and not re.search(pdef.pattern, val):
                            violations.append(
                                OntologyViolationError("PATTERN_VIOLATION", f"Property {prop_name} value {val!r} does not match {pdef.pattern}", str(node.id))
                            )

        # 2. Validate relationships, endpoints, irreflexivity, cardinality
        out_counts: dict[tuple[Any, str], int] = {}
        in_counts: dict[tuple[Any, str], int] = {}

        for edge in graph._edges.values():
            src_node = graph.get_node(edge.src)
            dst_node = graph.get_node(edge.dst)
            rel_def = self.relationships.get(edge.label)

            if rel_def:
                # Irreflexivity check
                if rel_def.is_irreflexive and edge.src == edge.dst:
                    violations.append(
                        OntologyViolationError("IRREFLEXIVE_VIOLATION", f"Relationship {edge.label} cannot be self-referential", str(edge.id))
                    )
                # Endpoint type check
                if src_node and src_node.label and rel_def.source_type != "Node":
                    if not self.is_subtype_of(src_node.label, rel_def.source_type):
                        violations.append(
                            OntologyViolationError("INVALID_SOURCE_TYPE", f"Source {src_node.label} is not a {rel_def.source_type}", str(edge.id))
                        )
                if dst_node and dst_node.label and rel_def.target_type != "Node":
                    if not self.is_subtype_of(dst_node.label, rel_def.target_type):
                        violations.append(
                            OntologyViolationError("INVALID_TARGET_TYPE", f"Target {dst_node.label} is not a {rel_def.target_type}", str(edge.id))
                        )

                out_counts[(edge.src, edge.label)] = out_counts.get((edge.src, edge.label), 0) + 1
                in_counts[(edge.dst, edge.label)] = in_counts.get((edge.dst, edge.label), 0) + 1

        # Cardinality maximums check
        for (src_id, rlabel), cnt in out_counts.items():
            rel_def = self.relationships.get(rlabel)
            if rel_def and rel_def.cardinality.max_outgoing is not None:
                if cnt > rel_def.cardinality.max_outgoing:
                    violations.append(
                        OntologyViolationError("MAX_OUTGOING_EXCEEDED", f"{rlabel} count {cnt} exceeds max {rel_def.cardinality.max_outgoing}", str(src_id))
                    )

        for (dst_id, rlabel), cnt in in_counts.items():
            rel_def = self.relationships.get(rlabel)
            if rel_def and rel_def.cardinality.max_incoming is not None:
                if cnt > rel_def.cardinality.max_incoming:
                    violations.append(
                        OntologyViolationError("MAX_INCOMING_EXCEEDED", f"{rlabel} count {cnt} exceeds max {rel_def.cardinality.max_incoming}", str(dst_id))
                    )

        return violations
