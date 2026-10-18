"""Physical execution package for GQL-Core."""

from gql_core.physical.engine import (
    explain_plan,
    execute_physical_plan,
    optimize_plan,
)
from gql_core.physical.evaluator import eval_predicate, eval_value

__all__ = [
    "eval_predicate",
    "eval_value",
    "execute_physical_plan",
    "explain_plan",
    "optimize_plan",
]
