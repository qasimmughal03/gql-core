"""Inventory of LDBC SNB Interactive v1 Read Queries.

Documents semantic compatibility across all 21 official read queries (14 Complex, 7 Short),
classified strictly into four semantic categories:
- Category A: Exact supported official operation
- Category B: Semantically equivalent translation
- Category C: Simplified or partially equivalent adaptation (reported separately, NOT an official pass)
- Category D: Unsupported operation
"""

from __future__ import annotations

from typing import Any

SNB_READ_QUERY_INVENTORY: list[dict[str, Any]] = [
    # ── Short Queries (IS1 - IS7) ──────────────────────────────────
    {
        "query_id": "IS1",
        "name": "Profile of a person",
        "family": "1-hop lookup",
        "semantic_category": "A",
        "category_description": "Exact supported official operation",
        "status": "executable",
        "unsupported_reason": None,
        "official_cypher": (
            "MATCH (n:Person {id: $personId})-[:IS_LOCATED_IN]->(p:City)\n"
            "RETURN n.firstName AS firstName,\n"
            "       n.lastName AS lastName,\n"
            "       n.birthday AS birthday,\n"
            "       n.locationIP AS locationIP,\n"
            "       n.browserUsed AS browserUsed,\n"
            "       p.id AS cityId,\n"
            "       n.gender AS gender,\n"
            "       n.creationDate AS creationDate"
        ),
        "adapted_cypher": (
            "MATCH (n:Person {id: $personId})-[:IS_LOCATED_IN]->(p:City) "
            "RETURN n.firstName AS firstName, n.lastName AS lastName, n.birthday AS birthday, "
            "n.locationIP AS locationIP, n.browserUsed AS browserUsed, p.id AS cityId, "
            "n.gender AS gender, n.creationDate AS creationDate"
        ),
        "semantic_notes": "Identical semantics to official LDBC query. Direct 1-hop outgoing pattern lookup with property projection.",
    },
    {
        "query_id": "IS2",
        "name": "Recent messages of a person",
        "family": "Multi-clause chaining / RPQ",
        "semantic_category": "D",
        "category_description": "Unsupported operation",
        "status": "unsupported",
        "unsupported_reason": "WITH_CLAUSE_CHAINING",
        "official_cypher": (
            "MATCH (:Person {id: $personId})<-[:HAS_CREATOR]-(message:Message)\n"
            "WITH message\n"
            "ORDER BY message.creationDate DESC, message.id DESC\n"
            "LIMIT 10\n"
            "MATCH (message)-[:REPLY_OF*0..]->(post:Post)\n"
            "RETURN message.id AS messageId,\n"
            "       coalesce(message.content, message.imageFile) AS messageContent,\n"
            "       message.creationDate AS messageCreationDate,\n"
            "       post.id AS originalPostId,\n"
            "       post.hasCreator.id AS originalPostAuthorId,\n"
            "       post.hasCreator.firstName AS originalPostAuthorFirstName,\n"
            "       post.hasCreator.lastName AS originalPostAuthorLastName"
        ),
        "adapted_cypher": None,
        "semantic_notes": "Requires WITH clause pipeline, multi-clause MATCH chaining, coalesce(), and RPQ composition.",
    },
    {
        "query_id": "IS3",
        "name": "Friends of a person",
        "family": "1-hop undirected join",
        "semantic_category": "B",
        "category_description": "Semantically equivalent translation",
        "status": "executable",
        "unsupported_reason": None,
        "official_cypher": (
            "MATCH (n:Person {id: $personId})-[r:KNOWS]-(friend:Person)\n"
            "RETURN friend.id AS personId,\n"
            "       friend.firstName AS firstName,\n"
            "       friend.lastName AS lastName,\n"
            "       r.creationDate AS friendshipCreationDate\n"
            "ORDER BY friendshipCreationDate DESC, toInteger(personId) ASC"
        ),
        "adapted_cypher": (
            "MATCH (n:Person {id: $personId})-[r:KNOWS]-(friend:Person) "
            "RETURN friend.id AS personId, friend.firstName AS firstName, "
            "friend.lastName AS lastName, r.creationDate AS friendshipCreationDate "
            "ORDER BY friendshipCreationDate DESC, personId ASC"
        ),
        "semantic_notes": (
            "Semantically equivalent: In GQL-Core, personId is stored as native 64-bit integer, "
            "so 'personId ASC' produces the exact same total ordering as 'toInteger(personId) ASC'."
        ),
    },
    {
        "query_id": "IS4",
        "name": "Content of a message",
        "family": "Single-node lookup",
        "semantic_category": "D",
        "category_description": "Unsupported operation",
        "status": "unsupported",
        "unsupported_reason": "UNSUPPORTED_FUNCTION_COALESCE",
        "official_cypher": (
            "MATCH (m:Message {id: $messageId})\n"
            "RETURN coalesce(m.content, m.imageFile) AS messageContent,\n"
            "       m.creationDate AS messageCreationDate"
        ),
        "adapted_cypher": None,
        "semantic_notes": "Requires coalesce() over polymorphous Message (Post or Comment) properties.",
    },
    {
        "query_id": "IS5",
        "name": "Creator of a message",
        "family": "1-hop lookup",
        "semantic_category": "C",
        "category_description": "Simplified or partially equivalent adaptation",
        "status": "executable",
        "unsupported_reason": None,
        "official_cypher": (
            "MATCH (m:Message {id: $messageId})-[:HAS_CREATOR]->(p:Person)\n"
            "RETURN p.id AS personId, p.firstName AS firstName, p.lastName AS lastName"
        ),
        "adapted_cypher": (
            "MATCH (m:Post {id: $messageId})-[:HAS_CREATOR]->(p:Person) "
            "RETURN p.id AS personId, p.firstName AS firstName, p.lastName AS lastName"
        ),
        "semantic_notes": (
            "PARTIAL ADAPTATION (NOT an official pass): Official query operates on abstract 'Message', "
            "which covers both 'Post' and 'Comment'. The adaptation restricts the lookup to 'Post', "
            "producing empty results if $messageId is a Comment."
        ),
    },
    {
        "query_id": "IS6",
        "name": "Forum of a message",
        "family": "Multi-hop path / RPQ",
        "semantic_category": "D",
        "category_description": "Unsupported operation",
        "status": "unsupported",
        "unsupported_reason": "ZERO_LENGTH_RPQ_COMPOSITION",
        "official_cypher": (
            "MATCH (m:Message {id: $messageId})-[:REPLY_OF*0..]->(p:Post)<-[:CONTAINER_OF]-(f:Forum)-[:HAS_MODERATOR]->(mod:Person)\n"
            "RETURN f.id AS forumId, f.title AS forumTitle, mod.id AS moderatorId, mod.firstName AS moderatorFirstName, mod.lastName AS moderatorLastName"
        ),
        "adapted_cypher": None,
        "semantic_notes": "Requires RPQ with zero-length bound (:REPLY_OF*0..) to traverse from Comment to root Post.",
    },
    {
        "query_id": "IS7",
        "name": "Replies of a message",
        "family": "Optional join / conditional",
        "semantic_category": "D",
        "category_description": "Unsupported operation",
        "status": "unsupported",
        "unsupported_reason": "OPTIONAL_MATCH_AND_CASE",
        "official_cypher": (
            "MATCH (m:Message {id: $messageId})<-[:REPLY_OF]-(c:Comment)-[:HAS_CREATOR]->(p:Person)\n"
            "OPTIONAL MATCH (m)-[:HAS_CREATOR]->(a:Person)-[r:KNOWS]-(p)\n"
            "RETURN c.id AS commentId, c.content AS commentContent, c.creationDate AS commentCreationDate, "
            "p.id AS replyAuthorId, p.firstName AS replyAuthorFirstName, p.lastName AS replyAuthorLastName, "
            "CASE WHEN r IS NULL THEN false ELSE true END AS replyAuthorKnowsOriginalMessageAuthor"
        ),
        "adapted_cypher": None,
        "semantic_notes": "Requires OPTIONAL MATCH and CASE WHEN conditional expression for author relationship test.",
    },

    # ── Complex Queries (IC1 - IC14) ──────────────────────────────
    {
        "query_id": "IC1",
        "name": "Friends with certain name",
        "family": "Variable-path / shortest-path",
        "semantic_category": "D",
        "category_description": "Unsupported operation",
        "status": "unsupported",
        "unsupported_reason": "SHORTEST_PATH_AND_WITH",
        "official_cypher": (
            "MATCH (p:Person {id: $personId})\n"
            "MATCH path = shortestPath((p)-[:KNOWS*1..3]-(friend:Person))\n"
            "WHERE friend.firstName = $firstName\n"
            "WITH friend, length(path) AS distance\n"
            "RETURN friend.id AS friendId, distance ..."
        ),
        "adapted_cypher": None,
        "semantic_notes": "Requires shortestPath() with variable hops (1..3), WITH clauses, and list projections.",
    },
    {
        "query_id": "IC2",
        "name": "Recent messages by your friends",
        "family": "2-hop join with filter",
        "semantic_category": "C",
        "category_description": "Simplified or partially equivalent adaptation",
        "status": "executable",
        "unsupported_reason": None,
        "official_cypher": (
            "MATCH (:Person {id: $personId})-[:KNOWS]-(friend:Person)<-[:HAS_CREATOR]-(message:Message)\n"
            "WHERE message.creationDate <= $maxDate\n"
            "RETURN friend.id AS personId,\n"
            "       friend.firstName AS personFirstName,\n"
            "       friend.lastName AS personLastName,\n"
            "       message.id AS postOrCommentId,\n"
            "       coalesce(message.content, message.imageFile) AS postOrCommentContent,\n"
            "       message.creationDate AS postOrCommentCreationDate\n"
            "ORDER BY postOrCommentCreationDate DESC, postOrCommentId ASC\n"
            "LIMIT 20"
        ),
        "adapted_cypher": (
            "MATCH (:Person {id: $personId})-[:KNOWS]-(friend:Person)<-[:HAS_CREATOR]-(message:Post) "
            "WHERE message.creationDate <= $maxDate "
            "RETURN friend.id AS personId, friend.firstName AS personFirstName, "
            "friend.lastName AS personLastName, message.id AS postOrCommentId, "
            "message.content AS postOrCommentContent, message.creationDate AS postOrCommentCreationDate "
            "ORDER BY postOrCommentCreationDate DESC, postOrCommentId ASC "
            "LIMIT 20"
        ),
        "semantic_notes": (
            "PARTIAL ADAPTATION (NOT an official pass): Adapts 'Message' to 'Post' only (omitting Comments) "
            "and replaces coalesce(content, imageFile) with content only."
        ),
    },
    {
        "query_id": "IC3",
        "name": "Friends that visited countries X and Y",
        "family": "Recursive path / grouping",
        "semantic_category": "D",
        "category_description": "Unsupported operation",
        "status": "unsupported",
        "unsupported_reason": "WITH_AND_COLLECT",
        "official_cypher": "Requires multi-hop path (1..2), WITH clause aggregation, and CASE WHEN filtering.",
        "adapted_cypher": None,
        "semantic_notes": "Requires 2-hop traversal, WITH clauses, and distinct message-in-country count aggregation.",
    },
    {
        "query_id": "IC4",
        "name": "New topics",
        "family": "Aggregation / Grouping",
        "semantic_category": "D",
        "category_description": "Unsupported operation",
        "status": "unsupported",
        "unsupported_reason": "WITH_AND_CASE",
        "official_cypher": "Requires WITH clause, CASE WHEN, and date arithmetic.",
        "adapted_cypher": None,
        "semantic_notes": "Requires date range filtering, WITH aggregation, and tag post count subtraction.",
    },
    {
        "query_id": "IC5",
        "name": "New groups",
        "family": "Aggregation / Grouping",
        "semantic_category": "D",
        "category_description": "Unsupported operation",
        "status": "unsupported",
        "unsupported_reason": "WITH_AND_OPTIONAL_MATCH",
        "official_cypher": "Requires WITH, OPTIONAL MATCH, and COUNT aggregation on member posts.",
        "adapted_cypher": None,
        "semantic_notes": "Requires OPTIONAL MATCH and group aggregation.",
    },
    {
        "query_id": "IC6",
        "name": "Tag co-occurrence",
        "family": "Multi-hop path / Grouping",
        "semantic_category": "D",
        "category_description": "Unsupported operation",
        "status": "unsupported",
        "unsupported_reason": "WITH_AND_UNWIND",
        "official_cypher": "Requires 2-hop KNOWS path, WITH clause, and tag co-occurrence aggregation.",
        "adapted_cypher": None,
        "semantic_notes": "Requires 2-hop path and co-occurrence aggregation.",
    },
    {
        "query_id": "IC7",
        "name": "Recent likes",
        "family": "Multi-hop join / Aggregation",
        "semantic_category": "D",
        "category_description": "Unsupported operation",
        "status": "unsupported",
        "unsupported_reason": "WITH_AND_HEAD",
        "official_cypher": "Requires WITH clause, head() list function, and date difference arithmetic.",
        "adapted_cypher": None,
        "semantic_notes": "Requires list functions, head(), and timestamp math.",
    },
    {
        "query_id": "IC8",
        "name": "Recent replies",
        "family": "3-hop join with ordering",
        "semantic_category": "C",
        "category_description": "Simplified or partially equivalent adaptation",
        "status": "executable",
        "unsupported_reason": None,
        "official_cypher": (
            "MATCH (start:Person {id: $personId})<-[:HAS_CREATOR]-(:Message)<-[:REPLY_OF]-(comment:Comment)-[:HAS_CREATOR]->(person:Person)\n"
            "RETURN person.id AS personId,\n"
            "       person.firstName AS personFirstName,\n"
            "       person.lastName AS personLastName,\n"
            "       comment.creationDate AS commentCreationDate,\n"
            "       comment.id AS commentId,\n"
            "       comment.content AS commentContent\n"
            "ORDER BY commentCreationDate DESC, commentId ASC\n"
            "LIMIT 20"
        ),
        "adapted_cypher": (
            "MATCH (start:Person {id: $personId})<-[:HAS_CREATOR]-(post:Post)<-[:REPLY_OF]-(comment:Comment)-[:HAS_CREATOR]->(person:Person) "
            "RETURN person.id AS personId, person.firstName AS personFirstName, "
            "person.lastName AS personLastName, comment.creationDate AS commentCreationDate, "
            "comment.id AS commentId, comment.content AS commentContent "
            "ORDER BY commentCreationDate DESC, commentId ASC "
            "LIMIT 20"
        ),
        "semantic_notes": (
            "PARTIAL ADAPTATION (NOT an official pass): In the official query, (:Message) covers replies to "
            "both Posts and Comments (nested threads). The adaptation limits the intermediate node to 'Post', "
            "omitting comments replying to other comments."
        ),
    },
    {
        "query_id": "IC9",
        "name": "Recent messages by friends or friends of friends",
        "family": "Recursive path (1..2)",
        "semantic_category": "D",
        "category_description": "Unsupported operation",
        "status": "unsupported",
        "unsupported_reason": "WITH_AND_UNWIND",
        "official_cypher": "Requires variable-length path (1..2), WITH clause, and UNWIND.",
        "adapted_cypher": None,
        "semantic_notes": "Requires variable path (1..2) and message ordering.",
    },
    {
        "query_id": "IC10",
        "name": "Friend recommendation",
        "family": "Recursive path / Scoring",
        "semantic_category": "D",
        "category_description": "Unsupported operation",
        "status": "unsupported",
        "unsupported_reason": "WITH_AND_OPTIONAL_MATCH",
        "official_cypher": "Requires 2-hop path, OPTIONAL MATCH, and birthday month calculation.",
        "adapted_cypher": None,
        "semantic_notes": "Requires 2-hop path, month extraction, and post similarity scoring.",
    },
    {
        "query_id": "IC11",
        "name": "Job referral",
        "family": "Recursive path / Temporal",
        "semantic_category": "D",
        "category_description": "Unsupported operation",
        "status": "unsupported",
        "unsupported_reason": "WITH_CLAUSE",
        "official_cypher": "Requires variable path (1..2), WORK_AT relationship filtering, and WITH.",
        "adapted_cypher": None,
        "semantic_notes": "Requires variable path (1..2), WORK_AT relationship filtering, and WITH.",
    },
    {
        "query_id": "IC12",
        "name": "Expert search",
        "family": "Recursive path / Subqueries",
        "semantic_category": "D",
        "category_description": "Unsupported operation",
        "status": "unsupported",
        "unsupported_reason": "WITH_AND_COLLECT",
        "official_cypher": "Requires 1-hop KNOWS, tag hierarchy traversal, and collect() aggregation.",
        "adapted_cypher": None,
        "semantic_notes": "Requires 1-hop KNOWS, tag hierarchy traversal, and collect() aggregation.",
    },
    {
        "query_id": "IC13",
        "name": "Single-pair shortest path",
        "family": "Shortest path",
        "semantic_category": "D",
        "category_description": "Unsupported operation",
        "status": "unsupported",
        "unsupported_reason": "SHORTEST_PATH_FUNCTION",
        "official_cypher": "Requires shortestPath((p1)-[:KNOWS*]-(p2)) function and CASE WHEN.",
        "adapted_cypher": None,
        "semantic_notes": "Requires shortestPath((p1)-[:KNOWS*]-(p2)) function and CASE WHEN.",
    },
    {
        "query_id": "IC14",
        "name": "Weighted paths",
        "family": "Weighted shortest path",
        "semantic_category": "D",
        "category_description": "Unsupported operation",
        "status": "unsupported",
        "unsupported_reason": "ALL_SHORTEST_PATHS_AND_UNWIND",
        "official_cypher": "Requires allShortestPaths(), UNWIND, and path weight calculation.",
        "adapted_cypher": None,
        "semantic_notes": "Requires allShortestPaths(), UNWIND, and path weight calculation.",
    },
]


def get_inventory_summary() -> dict[str, Any]:
    total = len(SNB_READ_QUERY_INVENTORY)
    cat_a = [q for q in SNB_READ_QUERY_INVENTORY if q["semantic_category"] == "A"]
    cat_b = [q for q in SNB_READ_QUERY_INVENTORY if q["semantic_category"] == "B"]
    cat_c = [q for q in SNB_READ_QUERY_INVENTORY if q["semantic_category"] == "C"]
    cat_d = [q for q in SNB_READ_QUERY_INVENTORY if q["semantic_category"] == "D"]

    return {
        "total_official_read_queries": total,
        "category_a_exact_supported_count": len(cat_a),
        "category_a_ids": [q["query_id"] for q in cat_a],
        "category_b_semantically_equivalent_count": len(cat_b),
        "category_b_ids": [q["query_id"] for q in cat_b],
        "official_supported_pass_count": len(cat_a) + len(cat_b),
        "official_supported_ids": [q["query_id"] for q in cat_a + cat_b],
        "category_c_simplified_adaptation_count": len(cat_c),
        "category_c_ids": [q["query_id"] for q in cat_c],
        "category_d_unsupported_count": len(cat_d),
        "category_d_ids": [q["query_id"] for q in cat_d],
        "official_supported_pct": round(((len(cat_a) + len(cat_b)) / total) * 100.0, 2),
    }
