"""Logical-Reasoning Benchmark (LRB).

A second class of queries beyond `benchmark.queries.QUERIES`. Each LR query
deliberately exercises a *reasoning pattern* the simple lookup queries don't
— conjunction over shared variables, transitive closure, multi-edge
constraints, heterogeneous-path composition, and RPQ + numeric filters.

Why this matters: the simple Q1–Q5 set verifies that the executor produces
correct rows for direct relational queries. LRB demonstrates that the engine
can answer questions that *require* the graph model — questions where SQL
either needs a `WITH RECURSIVE`, a multi-way self-join, or several `UNION ALL`
branches to express the same intent.

Captain identification is intentionally avoided here. cricsheet does not
ship a canonical per-match captain field, so the parser's "first-listed
player" heuristic is unreliable on real data. LRB queries depend only on
edges whose semantics are unambiguous: BATTED_IN, BOWLED_IN, PLAYED_AT,
TEAMMATES_WITH, NEXT_DELIVERY.
"""

from __future__ import annotations

LR_QUERIES: list[dict] = [
    {
        "name": "LR1_all_rounders",
        "purpose": (
            "Conjunction over shared variables: players who both batted AND "
            "bowled in the same match. Tests multi-pattern join with two "
            "shared bindings (p, m)."
        ),
        "reasoning_pattern": "conjunctive multi-pattern",
        "cypher": (
            "MATCH (p:Player)-[b:BATTED_IN]->(m:Match), (p)-[w:BOWLED_IN]->(m) "
            "WHERE b.runs > 0 AND w.wickets > 0 "
            "RETURN p.name AS allrounder, COUNT(m) AS matches "
            "ORDER BY matches DESC LIMIT 10"
        ),
        # SQL: self-join batted_in × bowled_in on (player_id, match_id).
        # In SQL this is one INNER JOIN — but the relational schema must
        # already have separate batted_in and bowled_in tables, and the
        # query must explicitly join on both columns. In Cypher the join
        # is implicit from the shared (p, m) variables in two patterns.
        "sql": (
            "SELECT pl.name AS allrounder, COUNT(DISTINCT b.match_id) AS matches "
            "FROM batted_in b "
            "JOIN bowled_in w ON w.player_id = b.player_id AND w.match_id = b.match_id "
            "JOIN players pl ON pl.id = b.player_id "
            "WHERE b.runs > 0 AND w.wickets > 0 "
            "GROUP BY pl.id, pl.name "
            "ORDER BY matches DESC, pl.name ASC LIMIT 10"
        ),
        "key_columns": ("allrounder", "matches"),
    },
    {
        "name": "LR2_teammates_within_two_hops",
        "purpose": (
            "Bounded transitive closure: players reachable from a seed via "
            "1 OR 2 TEAMMATES_WITH hops (undirected). Tests RPQ bounded "
            "Kleene over an undirected edge."
        ),
        "reasoning_pattern": "bounded transitive closure (RPQ)",
        "cypher": (
            "MATCH (p1:Player)-[:TEAMMATES_WITH*1..2]-(p2:Player) "
            'WHERE p1.name = "Babar Azam" '
            "RETURN p2.name AS within_2_hops "
            "ORDER BY within_2_hops ASC"
        ),
        # SQL: recursive CTE. The CASE expressions are needed because we
        # store TEAMMATES_WITH canonically (player_a_id < player_b_id);
        # for undirected traversal we have to check both columns. Note
        # the explicit depth bound and seed-exclusion to mirror Cypher.
        "sql": (
            "WITH RECURSIVE reach(node, depth) AS ( "
            "  SELECT CASE WHEN player_a_id = (SELECT id FROM players WHERE name='Babar Azam') "
            "              THEN player_b_id ELSE player_a_id END AS node, 1 AS depth "
            "  FROM teammates_with "
            "  WHERE player_a_id = (SELECT id FROM players WHERE name='Babar Azam') "
            "     OR player_b_id = (SELECT id FROM players WHERE name='Babar Azam') "
            "  UNION "
            "  SELECT CASE WHEN t.player_a_id = r.node THEN t.player_b_id ELSE t.player_a_id END, "
            "         r.depth + 1 "
            "  FROM teammates_with t JOIN reach r "
            "       ON (t.player_a_id = r.node OR t.player_b_id = r.node) "
            "  WHERE r.depth < 2 "
            ") "
            "SELECT DISTINCT pl.name AS within_2_hops "
            "FROM reach r JOIN players pl ON pl.id = r.node "
            "WHERE pl.name != 'Babar Azam' "
            "ORDER BY within_2_hops ASC"
        ),
        "key_columns": ("within_2_hops",),
    },
    {
        "name": "LR3_test_centurions",
        "purpose": (
            "Multi-edge constraint + format filter: players who scored a "
            "century (runs >= 100) in a Test match. Tests numeric threshold "
            "predicates over an edge property combined with a node property."
        ),
        "reasoning_pattern": "multi-edge constraint with threshold",
        "cypher": (
            "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
            'WHERE r.runs >= 100 AND m.format = "Test" '
            "RETURN p.name AS centurion, COUNT(m) AS test_hundreds "
            "ORDER BY test_hundreds DESC, centurion ASC LIMIT 10"
        ),
        "sql": (
            "SELECT pl.name AS centurion, COUNT(*) AS test_hundreds "
            "FROM batted_in b "
            "JOIN players pl ON pl.id = b.player_id "
            "JOIN matches m ON m.id = b.match_id "
            "WHERE b.runs >= 100 AND m.format = 'Test' "
            "GROUP BY pl.id, pl.name "
            "ORDER BY test_hundreds DESC, pl.name ASC LIMIT 10"
        ),
        "key_columns": ("centurion", "test_hundreds"),
    },
    {
        "name": "LR4_co_venue_batters",
        "purpose": (
            "Heterogeneous-path composition: players who have batted at a "
            "venue where Babar Azam also batted. Joins on a shared Venue "
            "node across two independent path patterns. Tests inequality "
            "filter (`!=`) and 4-edge graph composition."
        ),
        "reasoning_pattern": "heterogeneous-path composition (self-join on venue)",
        "cypher": (
            "MATCH (p1:Player)-[:BATTED_IN]->(m1:Match)-[:PLAYED_AT]->(v:Venue), "
            "      (p2:Player)-[:BATTED_IN]->(m2:Match)-[:PLAYED_AT]->(v:Venue) "
            'WHERE p1.name = "Babar Azam" AND p2.name != "Babar Azam" '
            "RETURN p2.name AS co_venue_batter, COUNT(v) AS shared_venue_instances "
            "ORDER BY shared_venue_instances DESC, co_venue_batter ASC LIMIT 10"
        ),
        "sql": (
            "SELECT pl2.name AS co_venue_batter, COUNT(*) AS shared_venue_instances "
            "FROM batted_in b1 "
            "JOIN players pl1 ON pl1.id = b1.player_id "
            "JOIN matches m1 ON m1.id = b1.match_id "
            "JOIN venues v ON v.id = m1.venue_id "
            "JOIN matches m2 ON m2.venue_id = v.id "
            "JOIN batted_in b2 ON b2.match_id = m2.id "
            "JOIN players pl2 ON pl2.id = b2.player_id "
            "WHERE pl1.name = 'Babar Azam' AND pl2.name != 'Babar Azam' "
            "GROUP BY pl2.id, pl2.name "
            "ORDER BY shared_venue_instances DESC, pl2.name ASC LIMIT 10"
        ),
        "key_columns": ("co_venue_batter", "shared_venue_instances"),
    },
    {
        "name": "LR5_scoring_chain_from_first_ball",
        "purpose": (
            "RPQ + numeric filter: from a specific starting delivery, "
            "how many balls within 12 hops scored runs? Tests bounded "
            "Kleene plus a comparison operator (`runs_batter > 0`) on "
            "the target node. {start_id} is resolved at run time."
        ),
        "reasoning_pattern": "RPQ with target-side property filter",
        "cypher": (
            "MATCH (d1:Delivery)-[:NEXT_DELIVERY*1..12]->(d2:Delivery) "
            'WHERE d1.id = "{start_id}" AND d2.runs_batter > 0 '
            "RETURN COUNT(d2) AS scoring_balls"
        ),
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ( "
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT n.next_id, c.depth + 1 "
            "  FROM chain c JOIN next_delivery n ON n.prev_id = c.end_id "
            "  WHERE c.depth < 12 "
            ") "
            "SELECT COUNT(*) AS scoring_balls "
            "FROM chain c JOIN deliveries d ON d.id = c.end_id "
            "WHERE d.runs_batter > 0"
        ),
        "key_columns": ("scoring_balls",),
        "needs_start_id": True,
    },
]


def expressibility(query: dict) -> dict:
    """Same shape as benchmark.queries.expressibility — token count + recursion flag."""
    cypher_tokens = len(query["cypher"].split())
    sql_tokens = len(query["sql"].split())
    return {
        "cypher_tokens": cypher_tokens,
        "sql_tokens": sql_tokens,
        "ratio_sql_over_cypher": round(sql_tokens / cypher_tokens, 2),
        "sql_recursive": "WITH RECURSIVE" in query["sql"].upper(),
        "reasoning_pattern": query["reasoning_pattern"],
    }
