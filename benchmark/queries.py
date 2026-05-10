"""Paired GQL-Core / SQL queries for the benchmark.

For each query both engines must produce the same canonical row set; the
benchmark harness compares them as a correctness check before timing.

Q5 NOTE (Phase 3 decision): The blueprint's original Q5 used `[:BATTED_IN*]`
which is a vacuous Kleene-star (Player→Match is always one hop). We pick
Option B from the plan and exercise the genuine RPQ path through Delivery /
NEXT_DELIVERY instead. The bounded variant (`*1..3`) still demonstrates BFS;
the SQL equivalent requires WITH RECURSIVE with an explicit depth cap.
"""

from __future__ import annotations

QUERIES: list[dict] = [
    {
        "name": "Q1_career_runs",
        "purpose": "Top run scorers (per-player aggregate over BATTED_IN edges).",
        "cypher": (
            "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
            "RETURN p.name AS player, SUM(r.runs) AS career_runs "
            "ORDER BY career_runs DESC LIMIT 10"
        ),
        "sql": (
            "SELECT pl.name AS player, SUM(b.runs) AS career_runs "
            "FROM batted_in b JOIN players pl ON pl.id = b.player_id "
            "GROUP BY pl.id, pl.name "
            "ORDER BY career_runs DESC, pl.name ASC LIMIT 10"
        ),
        "key_columns": ("player", "career_runs"),
    },
    {
        "name": "Q2_best_bowling_at_karachi",
        "purpose": "Best single-match bowling figures filtered by venue city.",
        "cypher": (
            "MATCH (p:Player)-[r:BOWLED_IN]->(m:Match)-[:PLAYED_AT]->(v:Venue) "
            'WHERE v.city = "Karachi" '
            "RETURN p.name AS bowler, MAX(r.wickets) AS best_haul "
            "ORDER BY best_haul DESC LIMIT 5"
        ),
        "sql": (
            "SELECT pl.name AS bowler, MAX(b.wickets) AS best_haul "
            "FROM bowled_in b "
            "JOIN players pl ON pl.id = b.player_id "
            "JOIN matches m ON m.id = b.match_id "
            "JOIN venues v ON v.id = m.venue_id "
            "WHERE v.city = 'Karachi' "
            "GROUP BY pl.id, pl.name "
            "ORDER BY best_haul DESC, pl.name ASC LIMIT 5"
        ),
        "key_columns": ("bowler", "best_haul"),
    },
    {
        "name": "Q3_pakistan_captain_wins",
        "purpose": "Most-winning Pakistani captains.",
        "cypher": (
            "MATCH (p:Player)-[:CAPTAINED]->(m:Match) "
            'WHERE m.outcome_winner = "Pakistan" AND p.country = "PAK" '
            "RETURN p.name AS captain, COUNT(m) AS wins "
            "ORDER BY wins DESC LIMIT 5"
        ),
        "sql": (
            "SELECT pl.name AS captain, COUNT(*) AS wins "
            "FROM captained c "
            "JOIN players pl ON pl.id = c.player_id "
            "JOIN matches m ON m.id = c.match_id "
            "WHERE m.outcome_winner = 'Pakistan' AND pl.country = 'PAK' "
            "GROUP BY pl.id, pl.name "
            "ORDER BY wins DESC, pl.name ASC LIMIT 5"
        ),
        "key_columns": ("captain", "wins"),
    },
    {
        "name": "Q4_babar_partners",
        "purpose": "Babar Azam's most-frequent teammates (TEAMMATES_WITH undirected).",
        "cypher": (
            "MATCH (p1:Player)-[t:TEAMMATES_WITH]-(p2:Player) "
            'WHERE p1.name = "Babar Azam" '
            "RETURN p2.name AS partner, t.match_count AS shared "
            "ORDER BY shared DESC LIMIT 10"
        ),
        # Cypher's '-' is undirected; SQL must union both directions because
        # we only store one canonical row per pair.
        "sql": (
            "SELECT pl2.name AS partner, t.match_count AS shared "
            "FROM teammates_with t "
            "JOIN players pl1 ON pl1.id = t.player_a_id "
            "JOIN players pl2 ON pl2.id = t.player_b_id "
            "WHERE pl1.name = 'Babar Azam' "
            "UNION ALL "
            "SELECT pl1.name AS partner, t.match_count AS shared "
            "FROM teammates_with t "
            "JOIN players pl1 ON pl1.id = t.player_a_id "
            "JOIN players pl2 ON pl2.id = t.player_b_id "
            "WHERE pl2.name = 'Babar Azam' "
            "ORDER BY shared DESC, partner ASC LIMIT 10"
        ),
        "key_columns": ("partner", "shared"),
    },
    {
        "name": "Q5_rpq_next_delivery",
        "purpose": "Bounded Kleene-star RPQ: deliveries reachable within 3 hops.",
        "cypher": (
            "MATCH (d:Delivery)-[:NEXT_DELIVERY*1..3]->(d2:Delivery) "
            'WHERE d.id = "1000001:1:0.1" '
            "RETURN d.id AS start, COUNT(d2) AS reachable"
        ),
        "sql": (
            "WITH RECURSIVE chain(start_id, end_id, depth) AS ("
            "  SELECT prev_id, next_id, 1 FROM next_delivery "
            "  WHERE prev_id = '1000001:1:0.1' "
            "  UNION ALL "
            "  SELECT c.start_id, n.next_id, c.depth + 1 "
            "  FROM chain c JOIN next_delivery n ON n.prev_id = c.end_id "
            "  WHERE c.depth < 3"
            ") "
            "SELECT '1000001:1:0.1' AS start, COUNT(*) AS reachable FROM chain"
        ),
        "key_columns": ("start", "reachable"),
    },
]


def expressibility(query: dict) -> dict:
    """Cheap structural metrics — number of tokens (whitespace-split) and
    whether SQL needed WITH RECURSIVE. Not normative; the README explains.
    """
    cypher_tokens = len(query["cypher"].split())
    sql_tokens = len(query["sql"].split())
    return {
        "cypher_tokens": cypher_tokens,
        "sql_tokens": sql_tokens,
        "ratio_sql_over_cypher": round(sql_tokens / cypher_tokens, 2),
        "sql_recursive": "WITH RECURSIVE" in query["sql"].upper(),
    }
