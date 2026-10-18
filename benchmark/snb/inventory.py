"""Inventory of LDBC SNB Interactive v1 Read Queries.

Documents coverage across all 21 official read queries (14 Complex, 7 Short),
categorized by query family and language capability status in GQL-Core v0.2.0.
"""

from __future__ import annotations

from typing import Any

SNB_READ_QUERY_INVENTORY: list[dict[str, Any]] = [
    # ── Short Queries (IS1 - IS7) ──────────────────────────────────
    {
        "query_id": "IS1",
        "name": "Profile of a person",
        "family": "1-hop lookup",
        "status": "executable",
        "unsupported_reason": None,
        "adapted_cypher": (
            "MATCH (n:Person {id: $personId})-[:IS_LOCATED_IN]->(p:City) "
            "RETURN n.firstName AS firstName, n.lastName AS lastName, n.birthday AS birthday, "
            "n.locationIP AS locationIP, n.browserUsed AS browserUsed, p.id AS cityId, "
            "n.gender AS gender, n.creationDate AS creationDate"
        ),
        "notes": "Direct 1-hop outgoing pattern lookup with property projection.",
    },
    {
        "query_id": "IS2",
        "name": "Recent messages of a person",
        "family": "Multi-clause chaining / RPQ",
        "status": "unsupported",
        "unsupported_reason": "WITH_CLAUSE_CHAINING",
        "adapted_cypher": None,
        "notes": "Requires MATCH ... WITH ... ORDER BY ... LIMIT ... MATCH chaining and coalesce().",
    },
    {
        "query_id": "IS3",
        "name": "Friends of a person",
        "family": "1-hop undirected join",
        "status": "executable",
        "unsupported_reason": None,
        "adapted_cypher": (
            "MATCH (n:Person {id: $personId})-[r:KNOWS]-(friend:Person) "
            "RETURN friend.id AS personId, friend.firstName AS firstName, "
            "friend.lastName AS lastName, r.creationDate AS friendshipCreationDate "
            "ORDER BY friendshipCreationDate DESC, personId ASC"
        ),
        "notes": "Undirected single-hop relationship join with multi-column ORDER BY.",
    },
    {
        "query_id": "IS4",
        "name": "Content of a message",
        "family": "Single-node lookup",
        "status": "unsupported",
        "unsupported_reason": "UNSUPPORTED_FUNCTION_COALESCE",
        "adapted_cypher": None,
        "notes": "Requires coalesce(m.content, m.imageFile) over polymorphous Post/Comment message types.",
    },
    {
        "query_id": "IS5",
        "name": "Creator of a message",
        "family": "1-hop lookup",
        "status": "executable",
        "unsupported_reason": None,
        "adapted_cypher": (
            "MATCH (m:Post {id: $messageId})-[:HAS_CREATOR]->(p:Person) "
            "RETURN p.id AS personId, p.firstName AS firstName, p.lastName AS lastName"
        ),
        "notes": "Direct 1-hop lookup from message to author person.",
    },
    {
        "query_id": "IS6",
        "name": "Forum of a message",
        "family": "Multi-hop path / RPQ",
        "status": "unsupported",
        "unsupported_reason": "ZERO_LENGTH_RPQ_COMPOSITION",
        "adapted_cypher": None,
        "notes": "Requires composite path with zero-or-more quantifier (:REPLY_OF*0..).",
    },
    {
        "query_id": "IS7",
        "name": "Replies of a message",
        "family": "Optional join / conditional",
        "status": "unsupported",
        "unsupported_reason": "OPTIONAL_MATCH_AND_CASE",
        "adapted_cypher": None,
        "notes": "Requires OPTIONAL MATCH and CASE WHEN expression for author friendship check.",
    },

    # ── Complex Queries (IC1 - IC14) ──────────────────────────────
    {
        "query_id": "IC1",
        "name": "Friends with certain name",
        "family": "Variable-path / shortest-path",
        "status": "unsupported",
        "unsupported_reason": "SHORTEST_PATH_AND_WITH",
        "adapted_cypher": None,
        "notes": "Requires shortestPath() with bounded hops (1..3), WITH clauses, and list collections.",
    },
    {
        "query_id": "IC2",
        "name": "Recent messages by your friends",
        "family": "2-hop join with filter",
        "status": "executable",
        "unsupported_reason": None,
        "adapted_cypher": (
            "MATCH (:Person {id: $personId})-[:KNOWS]-(friend:Person)<-[:HAS_CREATOR]-(message:Post) "
            "WHERE message.creationDate <= $maxDate "
            "RETURN friend.id AS personId, friend.firstName AS personFirstName, "
            "friend.lastName AS personLastName, message.id AS postOrCommentId, "
            "message.content AS postOrCommentContent, message.creationDate AS postOrCommentCreationDate "
            "ORDER BY postOrCommentCreationDate DESC, postOrCommentId ASC "
            "LIMIT 20"
        ),
        "notes": "2-hop graph join, timestamp range predicate, multi-column sorting, and limit.",
    },
    {
        "query_id": "IC3",
        "name": "Friends and friends of friends that have been to countries X and Y",
        "family": "Recursive path / grouping",
        "status": "unsupported",
        "unsupported_reason": "WITH_AND_COLLECT",
        "adapted_cypher": None,
        "notes": "Requires multi-hop path (1..2), WITH clause aggregation, and CASE WHEN filtering.",
    },
    {
        "query_id": "IC4",
        "name": "New topics",
        "family": "Aggregation / Grouping",
        "status": "unsupported",
        "unsupported_reason": "WITH_AND_CASE",
        "adapted_cypher": None,
        "notes": "Requires WITH clause, CASE WHEN, and date arithmetic.",
    },
    {
        "query_id": "IC5",
        "name": "New groups",
        "family": "Aggregation / Grouping",
        "status": "unsupported",
        "unsupported_reason": "WITH_AND_OPTIONAL_MATCH",
        "adapted_cypher": None,
        "notes": "Requires WITH, OPTIONAL MATCH, and COUNT aggregation on member posts.",
    },
    {
        "query_id": "IC6",
        "name": "Tag co-occurrence",
        "family": "Multi-hop path / Grouping",
        "status": "unsupported",
        "unsupported_reason": "WITH_AND_UNWIND",
        "adapted_cypher": None,
        "notes": "Requires 2-hop KNOWS path, WITH clause, and tag co-occurrence aggregation.",
    },
    {
        "query_id": "IC7",
        "name": "Recent likes",
        "family": "Multi-hop join / Aggregation",
        "status": "unsupported",
        "unsupported_reason": "WITH_AND_HEAD",
        "adapted_cypher": None,
        "notes": "Requires WITH clause, head() list function, and date difference arithmetic.",
    },
    {
        "query_id": "IC8",
        "name": "Recent replies",
        "family": "3-hop join with ordering",
        "status": "executable",
        "unsupported_reason": None,
        "adapted_cypher": (
            "MATCH (start:Person {id: $personId})<-[:HAS_CREATOR]-(post:Post)<-[:REPLY_OF]-(comment:Comment)-[:HAS_CREATOR]->(person:Person) "
            "RETURN person.id AS personId, person.firstName AS personFirstName, "
            "person.lastName AS personLastName, comment.creationDate AS commentCreationDate, "
            "comment.id AS commentId, comment.content AS commentContent "
            "ORDER BY commentCreationDate DESC, commentId ASC "
            "LIMIT 20"
        ),
        "notes": "3-hop join through Post and Comment back to responding Person, with ordering and limit.",
    },
    {
        "query_id": "IC9",
        "name": "Recent messages by friends or friends of friends",
        "family": "Recursive path (1..2)",
        "status": "unsupported",
        "unsupported_reason": "WITH_AND_UNWIND",
        "adapted_cypher": None,
        "notes": "Requires variable-length path (1..2), WITH clause, and UNWIND.",
    },
    {
        "query_id": "IC10",
        "name": "Friend recommendation",
        "family": "Recursive path / Scoring",
        "status": "unsupported",
        "unsupported_reason": "WITH_AND_OPTIONAL_MATCH",
        "adapted_cypher": None,
        "notes": "Requires 2-hop path, OPTIONAL MATCH, and birthday month calculation.",
    },
    {
        "query_id": "IC11",
        "name": "Job referral",
        "family": "Recursive path / Temporal",
        "status": "unsupported",
        "unsupported_reason": "WITH_CLAUSE",
        "adapted_cypher": None,
        "notes": "Requires variable path (1..2), WORK_AT relationship filtering, and WITH.",
    },
    {
        "query_id": "IC12",
        "name": "Expert search",
        "family": "Recursive path / Subqueries",
        "status": "unsupported",
        "unsupported_reason": "WITH_AND_COLLECT",
        "adapted_cypher": None,
        "notes": "Requires 1-hop KNOWS, tag hierarchy traversal, and collect() aggregation.",
    },
    {
        "query_id": "IC13",
        "name": "Single-pair shortest path",
        "family": "Shortest path",
        "status": "unsupported",
        "unsupported_reason": "SHORTEST_PATH_FUNCTION",
        "adapted_cypher": None,
        "notes": "Requires shortestPath((p1)-[:KNOWS*]-(p2)) function and CASE WHEN.",
    },
    {
        "query_id": "IC14",
        "name": "Weighted paths",
        "family": "Weighted shortest path",
        "status": "unsupported",
        "unsupported_reason": "ALL_SHORTEST_PATHS_AND_UNWIND",
        "adapted_cypher": None,
        "notes": "Requires allShortestPaths(), UNWIND, and path weight calculation.",
    },
]


def get_inventory_summary() -> dict[str, Any]:
    total = len(SNB_READ_QUERY_INVENTORY)
    executable = [q for q in SNB_READ_QUERY_INVENTORY if q["status"] == "executable"]
    unsupported = [q for q in SNB_READ_QUERY_INVENTORY if q["status"] == "unsupported"]

    family_counts: dict[str, dict[str, int]] = {}
    for q in SNB_READ_QUERY_INVENTORY:
        fam = q["family"]
        if fam not in family_counts:
            family_counts[fam] = {"total": 0, "executable": 0, "unsupported": 0}
        family_counts[fam]["total"] += 1
        family_counts[fam][q["status"]] += 1

    unsupported_reasons: dict[str, int] = {}
    for q in unsupported:
        r = q["unsupported_reason"] or "UNKNOWN"
        unsupported_reasons[r] = unsupported_reasons.get(r, 0) + 1

    return {
        "total_queries": total,
        "executable_count": len(executable),
        "unsupported_count": len(unsupported),
        "executable_ids": [q["query_id"] for q in executable],
        "unsupported_ids": [q["query_id"] for q in unsupported],
        "family_breakdown": family_counts,
        "unsupported_reasons": unsupported_reasons,
    }
