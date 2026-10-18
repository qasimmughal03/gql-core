"""Declarative Datalog-like rule definitions and provenance tracking for ontology inference.

Supports:
- Facts: ground tuples of (predicate, args...)
- Atoms: rule premises/conclusions with variables (?x, ?y) and constants
- Rules: Head :- Body_1, Body_2, ... with stratified negation
- Provenance: tracks the derivation chain and rule name for every inferred fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Fact:
    """A ground assertion or derived truth."""
    predicate: str  # e.g. "rel", "has_type", "prop"
    args: tuple[Any, ...]
    is_inferred: bool = False
    rule_name: str | None = None
    evidence: tuple[Fact, ...] = ()

    def __str__(self) -> str:
        args_str = ", ".join(repr(a) for a in self.args)
        prefix = "[Inferred] " if self.is_inferred else ""
        return f"{prefix}{self.predicate}({args_str})"


@dataclass(frozen=True)
class Atom:
    """A premise or conclusion pattern containing variables (?x) or constants."""
    predicate: str
    args: tuple[Any, ...]
    is_negated: bool = False

    def is_ground(self) -> bool:
        return not any(isinstance(a, str) and a.startswith("?") for a in self.args)

    def __str__(self) -> str:
        args_str = ", ".join(str(a) for a in self.args)
        neg = "NOT " if self.is_negated else ""
        return f"{neg}{self.predicate}({args_str})"


@dataclass(frozen=True)
class InferenceRule:
    """A Datalog-like rule: head :- body_1, body_2, ..."""
    name: str
    head: Atom
    body: tuple[Atom, ...]
    description: str = ""

    def __post_init__(self) -> None:
        # Safety check: every variable in head must appear in at least one positive body atom
        head_vars = {a for a in self.head.args if isinstance(a, str) and a.startswith("?")}
        body_pos_vars = set()
        for b in self.body:
            if not b.is_negated:
                body_pos_vars.update(a for a in b.args if isinstance(a, str) and a.startswith("?"))
        unbound = head_vars - body_pos_vars
        if unbound:
            raise ValueError(f"Rule {self.name!r} is unsafe: head variables {sorted(unbound)} not in positive body atoms")

    def __str__(self) -> str:
        body_str = ", ".join(str(b) for b in self.body)
        return f"{self.name}: {self.head} :- {body_str}"


def make_subtype_rule(sub_type: str, super_type: str) -> InferenceRule:
    return InferenceRule(
        name=f"subtype_{sub_type}_to_{super_type}",
        head=Atom("has_type", ("?x", super_type)),
        body=(Atom("has_type", ("?x", sub_type)),),
        description=f"{sub_type} implies {super_type}",
    )


def make_inverse_rule(rel_name: str, inverse_name: str) -> InferenceRule:
    return InferenceRule(
        name=f"inverse_{rel_name}_{inverse_name}",
        head=Atom("rel", ("?y", inverse_name, "?x")),
        body=(Atom("rel", ("?x", rel_name, "?y")),),
        description=f"{rel_name}(x, y) implies {inverse_name}(y, x)",
    )


def make_symmetric_rule(rel_name: str) -> InferenceRule:
    return InferenceRule(
        name=f"symmetric_{rel_name}",
        head=Atom("rel", ("?y", rel_name, "?x")),
        body=(Atom("rel", ("?x", rel_name, "?y")),),
        description=f"{rel_name}(x, y) implies {rel_name}(y, x)",
    )


def make_transitive_rule(rel_name: str) -> InferenceRule:
    return InferenceRule(
        name=f"transitive_{rel_name}",
        head=Atom("rel", ("?x", rel_name, "?z")),
        body=(
            Atom("rel", ("?x", rel_name, "?y")),
            Atom("rel", ("?y", rel_name, "?z")),
        ),
        description=f"{rel_name}(x, y) and {rel_name}(y, z) implies {rel_name}(x, z)",
    )


def make_composition_rule(derived_name: str, rel1: str, rel2: str) -> InferenceRule:
    return InferenceRule(
        name=f"compose_{rel1}_{rel2}_to_{derived_name}",
        head=Atom("rel", ("?x", derived_name, "?z")),
        body=(
            Atom("rel", ("?x", rel1, "?y")),
            Atom("rel", ("?y", rel2, "?z")),
        ),
        description=f"{rel1}(x, y) and {rel2}(y, z) implies {derived_name}(x, z)",
    )
