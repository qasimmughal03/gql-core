"""Explicit openCypher error categories raised by the GQL-Core engine."""

from __future__ import annotations


class EntityNotFoundError(RuntimeError):
    """openCypher EntityNotFound: access to a deleted node or relationship."""


class ConstraintVerificationError(RuntimeError):
    """openCypher ConstraintVerificationFailed: e.g. deleting a node that still has relationships."""


class ProcedureError(Exception):
    """openCypher ProcedureError: unknown procedure."""


class ParameterMissingError(Exception):
    """openCypher ParameterMissing: a required query parameter was not supplied."""


class ArgumentError(ValueError):
    """openCypher ArgumentError: invalid argument value at runtime."""
