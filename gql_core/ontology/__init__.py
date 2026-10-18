"""Ontology domain model and schema package for GQL-Core."""

from gql_core.ontology.model import (
    CardinalityConstraint,
    EntityType,
    NodeType,
    PropertyDef,
    ReasoningMode,
    RelationshipType,
)
from gql_core.ontology.schema import OntologySchema, OntologyViolationError

__all__ = [
    "CardinalityConstraint",
    "EntityType",
    "NodeType",
    "OntologySchema",
    "OntologyViolationError",
    "PropertyDef",
    "ReasoningMode",
    "RelationshipType",
]
