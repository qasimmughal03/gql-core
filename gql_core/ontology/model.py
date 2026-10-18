"""Ontology domain models and declarative schema definitions for GQL-Core.

Supports:
- Entity types (properties, types, required/optional, nullability, subtypes/supertypes, abstract)
- Relationship types (source, target, cardinality min/max incoming/outgoing, inverse, symmetric,
  transitive, reflexive/irreflexive, asymmetric, functional, completeness assumption)
- Closed-world (CWA) vs Open-world (OWA) reasoning declarations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from gql_core.types import DataType


class ReasoningMode(str, Enum):
    CWA = "CWA"  # Closed-World Assumption (absence implies false)
    OWA = "OWA"  # Open-World Assumption (absence implies unknown)


@dataclass(frozen=True)
class PropertyDef:
    name: str
    type: DataType = DataType.STRING
    required: bool = False
    nullable: bool = True
    default: Any = None
    pattern: str | None = None
    enum_values: tuple[Any, ...] | None = None
    min_value: Any = None
    max_value: Any = None


@dataclass(frozen=True)
class CardinalityConstraint:
    min_outgoing: int | None = None
    max_outgoing: int | None = None
    min_incoming: int | None = None
    max_incoming: int | None = None


@dataclass(frozen=True)
class EntityType:
    name: str
    properties: dict[str, PropertyDef] = field(default_factory=dict)
    supertypes: tuple[str, ...] = ()
    subtypes: tuple[str, ...] = ()
    is_abstract: bool = False
    identity_prop: str = "id"


NodeType = EntityType  # Alias for property graph conventions


@dataclass(frozen=True)
class RelationshipType:
    name: str
    source_type: str
    target_type: str
    directed: bool = True
    cardinality: CardinalityConstraint = field(default_factory=CardinalityConstraint)
    properties: dict[str, PropertyDef] = field(default_factory=dict)
    inverse: str | None = None
    is_symmetric: bool = False
    is_transitive: bool = False
    is_reflexive: bool = False
    is_irreflexive: bool = True
    is_asymmetric: bool = False
    is_functional: bool = False  # max_outgoing == 1
    is_inverse_functional: bool = False  # max_incoming == 1
    disjoint_with: tuple[str, ...] = ()
    reasoning_mode: ReasoningMode = ReasoningMode.CWA
