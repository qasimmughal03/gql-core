"""Ontology inference package for GQL-Core."""

from gql_core.inference.engine import InferenceEngine
from gql_core.inference.rules import (
    Atom,
    Fact,
    InferenceRule,
    make_composition_rule,
    make_inverse_rule,
    make_subtype_rule,
    make_symmetric_rule,
    make_transitive_rule,
)

# Aliases for Datalog terminology
DatalogEngine = InferenceEngine
DatalogRule = InferenceRule
DatalogAtom = Atom
DatalogFact = Fact

__all__ = [
    "Atom",
    "DatalogAtom",
    "DatalogEngine",
    "DatalogFact",
    "DatalogRule",
    "Fact",
    "InferenceEngine",
    "InferenceRule",
    "make_composition_rule",
    "make_inverse_rule",
    "make_subtype_rule",
    "make_symmetric_rule",
    "make_transitive_rule",
]
