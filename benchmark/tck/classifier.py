"""Classification rules for openCypher TCK Scenarios.

Categorizes each scenario before or during evaluation:
- 'unsupported': Requires capabilities outside the declared GQL-Core language engine.
- 'claimed': Within the declared language engine, evaluated for 'passed' or 'failed'.
With the full multi-clause openCypher pipeline engine, all scenarios are executed directly.
"""

from __future__ import annotations

import re
from typing import Tuple


def classify_query(query: str) -> Tuple[bool, str | None]:
    """Check if query is within the declared GQL-Core language engine.
    
    Returns:
        (is_supported, reason_if_unsupported)
    """
    q = query.strip()
    if not q:
        return False, "EMPTY_QUERY"

    # 1. Multiple relationship type alternatives in patterns: [:A|B]
    if re.search(r":\s*[a-zA-Z0-9_]+\s*\|", q):
        return False, "MULTI_REL_TYPE_DISJUNCTION"

    # 2. Shortest path builtins
    if re.search(r"\b(?:shortestPath|allShortestPaths)\s*\(", q, re.I):
        return False, "SHORTEST_PATH_BUILTIN"

    # 3. Correlated subquery expressions: CALL { ... } or exists { ... }
    if re.search(r"\bCALL\s*\{", q, re.I):
        return False, "CORRELATED_SUBQUERY_CALL"
    if re.search(r"\bexists\s*\{", q, re.I):
        return False, "CORRELATED_SUBQUERY_EXISTS"

    # 4. Map projection shorthand: n { .prop, .* }
    if re.search(r"[a-zA-Z0-9_]+\s*\{\s*(?:\.|\*)", q):
        return False, "MAP_PROJECTION"

    # 5. Unsupported clauses
    if re.search(r"\bFOREACH\s*\(", q, re.I):
        return False, "FOREACH_CLAUSE"
    if re.search(r"\bLOAD\s+CSV\b", q, re.I):
        return False, "LOAD_CSV_CLAUSE"
    if re.search(r"\bSTART\s+[a-zA-Z0-9_]+\s*=", q, re.I):
        return False, "START_CLAUSE"

    return True, None
