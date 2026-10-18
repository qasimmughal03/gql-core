"""Classification rules for openCypher TCK Scenarios.

Categorizes each scenario before or during evaluation:
- 'unsupported': Requires capabilities outside the declared GQL-Core v0.2.0 language subset.
- 'claimed': Within the declared language subset, evaluated for 'passed' or 'failed'.
"""

from __future__ import annotations

import re
from typing import Tuple

# Keywords that indicate mutations or multi-clause chaining not in GQL-Core v0.2.0
UNSUPPORTED_KEYWORDS = [
    (re.compile(r"\bCREATE\b", re.I), "MUTATION_CREATE"),
    (re.compile(r"\bMERGE\b", re.I), "MUTATION_MERGE"),
    (re.compile(r"\bDELETE\b", re.I), "MUTATION_DELETE"),
    (re.compile(r"\bDETACH\b", re.I), "MUTATION_DETACH"),
    (re.compile(r"\bSET\b", re.I), "MUTATION_SET"),
    (re.compile(r"\bREMOVE\b", re.I), "MUTATION_REMOVE"),
    (re.compile(r"\bOPTIONAL\s+MATCH\b", re.I), "OPTIONAL_MATCH"),
    (re.compile(r"\bWITH\b", re.I), "WITH_CLAUSE"),
    (re.compile(r"\bUNWIND\b", re.I), "UNWIND_CLAUSE"),
    (re.compile(r"\bCALL\b", re.I), "CALL_PROCEDURE"),
    (re.compile(r"\bUNION\b", re.I), "UNION_CLAUSE"),
    (re.compile(r"\bCASE\b", re.I), "CASE_WHEN_EXPR"),
    (re.compile(r"\bshortestPath\b", re.I), "SHORTEST_PATH_FUNCTION"),
    (re.compile(r"\ballShortestPaths\b", re.I), "SHORTEST_PATH_FUNCTION"),
]

# Non-aggregate Cypher functions not supported in core GQL
UNSUPPORTED_FUNCTIONS = [
    "coalesce", "tointeger", "tofloat", "toboolean", "tostring",
    "exists", "size", "length", "keys", "labels", "nodes", "relationships",
    "type", "id", "collect", "range", "head", "tail", "last",
    "substring", "trim", "ltrim", "rtrim", "tolower", "toupper",
    "replace", "split", "reverse", "left", "right", "round", "ceil", "floor",
    "sqrt", "sign", "abs", "rand", "sin", "cos", "tan", "asin", "acos", "atan",
    "percentilecont", "percentiledisc", "stdev", "stdevp", "properties"
]

def classify_query(query: str) -> Tuple[bool, str | None]:
    """Check if query is within the claimed GQL-Core language subset.
    
    Returns:
        (is_supported, reason_if_unsupported)
    """
    q = query.strip()
    if not q:
        return False, "EMPTY_QUERY"

    # Check for standalone RETURN without MATCH
    if not re.search(r"\bMATCH\b", q, re.I):
        return False, "STANDALONE_RETURN_WITHOUT_MATCH"

    # Check for multiple MATCH clauses: MATCH ... MATCH ...
    matches = list(re.finditer(r"\bMATCH\b", q, re.I))
    if len(matches) > 1:
        return False, "MULTIPLE_MATCH_CLAUSES"

    # Check for path assignment: p = (a)-[]->(b)
    if re.search(r"\b[a-zA-Z0-9_]+\s*=\s*\(", q):
        return False, "PATH_VARIABLE_ASSIGNMENT"

    # Check for RPQ edge variable binding (e.g. -[r*1..2]->)
    if re.search(r"-\[[a-zA-Z0-9_]+\s*(?::[a-zA-Z0-9_]*)?\*", q):
        return False, "RPQ_EDGE_VARIABLE_LIST_BINDING"

    # Check for multiple labels on a node: (:A:B)
    if re.search(r"\([a-zA-Z0-9_]*:[a-zA-Z0-9_]+:[a-zA-Z0-9_]+", q):
        return False, "MULTI_LABEL_NODE_PATTERN"

    # Check for relationship type disjunction: [:A|:B]
    if re.search(r"-\[[^\]]*\|", q):
        return False, "RELATIONSHIP_TYPE_DISJUNCTION"

    # Check for inline relationship properties: -[r {prop: val}]-
    if re.search(r"-\[[^\]]*\{[^}]*\}", q):
        return False, "RELATIONSHIP_INLINE_PROPERTIES"

    # Check keyword clauses
    for regex, reason in UNSUPPORTED_KEYWORDS:
        if regex.search(q):
            return False, reason

    # Check for SKIP clause
    if re.search(r"\bSKIP\b", q, re.I):
        return False, "SKIP_CLAUSE"

    # Check for DISTINCT in RETURN
    if re.search(r"\bRETURN\s+DISTINCT\b", q, re.I):
        return False, "RETURN_DISTINCT"

    # Check for IS NULL / IS NOT NULL predicate (GQL-Core uses = null / != null)
    if re.search(r"\bIS\s+(?:NOT\s+)?NULL\b", q, re.I):
        return False, "IS_NULL_PREDICATE"

    # Check for IN list predicate
    if re.search(r"\bIN\s*\[", q, re.I):
        return False, "IN_LIST_PREDICATE"

    # Check for string predicates: STARTS WITH, ENDS WITH, CONTAINS
    if re.search(r"\b(STARTS\s+WITH|ENDS\s+WITH|CONTAINS)\b", q, re.I):
        return False, "STRING_PREDICATE"

    # Check for regex match =~
    if re.search(r"=~", q):
        return False, "REGEX_PREDICATE"

    # Check for parameterized queries ($param)
    if re.search(r"\$[a-zA-Z0-9_]+", q):
        return False, "PARAMETER_SUBSTITUTION"

    # Check functions
    q_lower = q.lower()
    for fn in UNSUPPORTED_FUNCTIONS:
        if re.search(rf"\b{fn}\s*\(", q_lower):
            return False, f"UNSUPPORTED_FUNCTION_{fn.upper()}"

    # Check list or map comprehensions: [x IN list | x] or [x IN list WHERE ... | x]
    if re.search(r"\[\s*[a-zA-Z0-9_]+\s+IN\s+", q, re.I):
        return False, "LIST_COMPREHENSION"

    # Check for RETURN *
    if re.search(r"\bRETURN\s+\*(?:\s|,|$)", q, re.I):
        return False, "RETURN_WILDCARD"

    # Check for label expressions in RETURN (e.g. RETURN a:B)
    if re.search(r"\bRETURN\b.*[a-zA-Z0-9_]+\s*:\s*[a-zA-Z0-9_]+", q, re.I):
        return False, "LABEL_PREDICATE_IN_RETURN"

    # Check for existential subquery in WHERE
    if re.search(r"\bexists\s*\{", q, re.I):
        return False, "EXISTENTIAL_SUBQUERY"

    # Check pattern expressions in WHERE: WHERE (a)-->() or WHERE (a)<-[]-() or WHERE NOT (a)-[]->()
    if re.search(r"\bWHERE\b.*(?:\([a-zA-Z0-9_:]*\)\s*<?-(?:\[|->|<-|-))", q, re.I | re.DOTALL):
        return False, "PATTERN_EXPRESSION_IN_WHERE"

    # Check for pattern comprehensions: [(n)-[r]->(m) | m.name]
    if re.search(r"\[\s*\([a-zA-Z0-9_:]*\)\s*<?-(?:\[|->|<-|-)", q, re.I):
        return False, "PATTERN_COMPREHENSION"

    # Check for list literals in RETURN: RETURN [n, r, m]
    if re.search(r"\bRETURN\s+\[", q, re.I):
        return False, "LIST_LITERAL_IN_RETURN"

    # Check for boolean or comparison expressions in RETURN: RETURN count(*) > 0
    if re.search(r"\bRETURN\b.*(?:<=|>=|!=|<>|<|>|=)", q, re.I):
        return False, "BOOLEAN_EXPRESSION_IN_RETURN"

    # Check for dynamic map/property subscripting in RETURN: RETURN n['name']
    if re.search(r"\bRETURN\b.*[a-zA-Z0-9_]\s*\[", q, re.I):
        return False, "DYNAMIC_PROPERTY_SUBSCRIPTING"

    # Check for label expressions in WHERE (e.g. WHERE a:Label or WHERE (a:Label))
    if re.search(r"\bWHERE\b.*(?:\b[a-zA-Z0-9_]+\s*:\s*[a-zA-Z0-9_]+|\([a-zA-Z0-9_]+\s*:\s*[a-zA-Z0-9_]+\))", q, re.I):
        return False, "WHERE_LABEL_PREDICATE"

    # Check for chained comparisons (e.g. 1 < n.num < 3)
    if re.search(r"(?:<=|>=|!=|<>|<|>|=)\s*[^<>=,\s]+\s*(?:<=|>=|!=|<>|<|>|=)", q):
        return False, "CHAINED_COMPARISON"

    # Check for arithmetic expressions in RETURN or ORDER BY
    if re.search(r"\b(?:RETURN|ORDER\s+BY)\b.*[a-zA-Z0-9_)]\s*[\+\*\/]\s*[a-zA-Z0-9_(]", q, re.I):
        return False, "ARITHMETIC_EXPRESSION"

    # Check for ORDER BY with aggregate calls (e.g. ORDER BY count(*), ORDER BY max(n))
    if re.search(r"\bORDER\s+BY\b.*(?:\bCOUNT|\bSUM|\bAVG|\bMIN|\bMAX)\s*\(", q, re.I):
        return False, "ORDER_BY_AGGREGATE_EXPRESSION"

    # Check for ref-to-ref comparisons in WHERE (e.g. WHERE a = b or WHERE a.x = b.x or WHERE a <> b)
    if re.search(r"\bWHERE\b.*(?:<=|>=|!=|<>|<|>|=)\s*[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)?(?!\s*\()(?!\b(?:true|false|null)\b)", q, re.I):
        return False, "REF_COMPARISON_IN_WHERE"

    # Check list subscripting: ref[0]
    if re.search(r"[a-zA-Z0-9_]\s*\[\s*[0-9]+\s*\]", q):
        return False, "LIST_SUBSCRIPTING"

    # Check map constructor/projection in RETURN: RETURN n { .name }
    if re.search(r"\bRETURN\b.*\{.*\}", q, re.I | re.DOTALL):
        return False, "MAP_PROJECTION"

    # Check COUNT(DISTINCT ...)
    if re.search(r"\bCOUNT\s*\(\s*DISTINCT\b", q, re.I):
        return False, "COUNT_DISTINCT"

    return True, None
