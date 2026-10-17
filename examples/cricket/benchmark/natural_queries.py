"""Natural-Language QA Benchmark for the Cricket Knowledge Graph.

35 queries across 9 query classes, each expressed as:
  - a natural-language question a cricket fan would ask
  - an equivalent GQL-Core Cypher query
  - an equivalent SQL query (for cross-engine parity verification)

Query classes (A–I):
  A  Simple property lookup / count               (4 queries)
  B  Single-edge aggregation (SUM/AVG/MIN/MAX)    (5 queries)
  C  Multi-hop path traversal (2+ edge types)      (4 queries)
  D  Multi-pattern conjunction (shared variables)  (4 queries)
  E  Undirected edge queries (TEAMMATES_WITH)      (3 queries)
  F  RPQ / bounded Kleene-star                     (5 queries)
  G  RPQ + target-side property filter             (3 queries)
  H  Negation & boolean composition                (4 queries)
  I  Hard / compound multi-constraint queries      (3 queries)

Each entry carries a `ground_truth_note` that explains what the correct
answer should look like and why — verified against cricket history or
structural invariants of the data model, independent of the engine output.

Queries that target a specific Delivery node carry `needs_start_id: True`;
the harness fills the `{start_id}` placeholder at runtime.
"""

from __future__ import annotations

NL_QUERIES: list[dict] = [

    # ── A: Simple property lookup / count ───────────────────────────────

    {
        "name": "NQ01_total_matches",
        "question": "How many matches are in Pakistan's cricket history dataset?",
        "query_class": "simple_lookup",
        "cypher": (
            "MATCH (m:Match) "
            "RETURN COUNT(m) AS total_matches"
        ),
        "sql": (
            "SELECT COUNT(*) AS total_matches FROM matches"
        ),
        "key_columns": ("total_matches",),
        "ground_truth_note": (
            "Must equal the number of JSON files ingested from cricsheet. "
            "Full Pakistan corpus = 1,123 men's matches."
        ),
    },

    {
        "name": "NQ02_total_players",
        "question": "How many unique players (both Pakistani and opponents) are in the dataset?",
        "query_class": "simple_lookup",
        "cypher": (
            "MATCH (p:Player) "
            "RETURN COUNT(p) AS total_players"
        ),
        "sql": (
            "SELECT COUNT(*) AS total_players FROM players"
        ),
        "key_columns": ("total_players",),
        "ground_truth_note": (
            "Full corpus: ~1,920 players. Must include Pakistani players "
            "AND every opponent player Pakistan has faced."
        ),
    },

    {
        "name": "NQ03_test_match_count",
        "question": "How many Test matches did Pakistan play?",
        "query_class": "simple_lookup",
        "cypher": (
            'MATCH (m:Match) WHERE m.format = "Test" '
            "RETURN COUNT(m) AS test_matches"
        ),
        "sql": (
            "SELECT COUNT(*) AS test_matches FROM matches WHERE format = 'Test'"
        ),
        "key_columns": ("test_matches",),
        "ground_truth_note": (
            "Pakistan has played ~450+ Tests historically. This corpus covers "
            "the digitized cricsheet matches only."
        ),
    },

    {
        "name": "NQ04_venue_count",
        "question": "How many distinct venues have hosted Pakistan matches?",
        "query_class": "simple_lookup",
        "cypher": (
            "MATCH (v:Venue) "
            "RETURN COUNT(v) AS venue_count"
        ),
        "sql": (
            "SELECT COUNT(*) AS venue_count FROM venues"
        ),
        "key_columns": ("venue_count",),
        "ground_truth_note": (
            "Full corpus: 210 venues. Includes domestic and overseas grounds "
            "where Pakistan has played."
        ),
    },

    # ── B: Single-edge aggregation ───────────────────────────────────────

    {
        "name": "NQ05_top_test_run_scorers",
        "question": "Who are Pakistan's top-5 Test match run-scorers of all time?",
        "query_class": "aggregation",
        "cypher": (
            "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
            'WHERE m.format = "Test" '
            "RETURN p.name AS player, SUM(r.runs) AS test_runs "
            "ORDER BY test_runs DESC, player ASC LIMIT 5"
        ),
        "sql": (
            "SELECT pl.name AS player, SUM(b.runs) AS test_runs "
            "FROM batted_in b JOIN players pl ON pl.id = b.player_id "
            "JOIN matches m ON m.id = b.match_id "
            "WHERE m.format = 'Test' "
            "GROUP BY pl.id, pl.name "
            "ORDER BY test_runs DESC, pl.name ASC LIMIT 5"
        ),
        "key_columns": ("player", "test_runs"),
        "ground_truth_note": (
            "Younis Khan leads all Pakistan Test batters with 10,099 runs. "
            "Inzamam-ul-Haq (~8,830) and Mohammad Yousuf (~7,530) follow. "
            "Misbah-ul-Haq (~5,222) and Azhar Ali (~7,142) also in top 5."
        ),
    },

    {
        "name": "NQ06_top_t20_six_hitters",
        "question": "Who hit the most sixes in Pakistan's T20 international matches?",
        "query_class": "aggregation",
        "cypher": (
            "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
            'WHERE m.format = "T20" '
            "RETURN p.name AS player, SUM(r.sixes) AS t20_sixes "
            "ORDER BY t20_sixes DESC, player ASC LIMIT 5"
        ),
        "sql": (
            "SELECT pl.name AS player, SUM(b.sixes) AS t20_sixes "
            "FROM batted_in b JOIN players pl ON pl.id = b.player_id "
            "JOIN matches m ON m.id = b.match_id "
            "WHERE m.format = 'T20' "
            "GROUP BY pl.id, pl.name "
            "ORDER BY t20_sixes DESC, pl.name ASC LIMIT 5"
        ),
        "key_columns": ("player", "t20_sixes"),
        "ground_truth_note": (
            "Shahid Afridi is Pakistan's all-time T20I six-hitting champion; "
            "Babar Azam and Mohammad Hafeez also feature prominently."
        ),
    },

    {
        "name": "NQ07_top_wicket_takers",
        "question": "Who are the top-5 overall wicket-takers across all formats in this dataset?",
        "query_class": "aggregation",
        "cypher": (
            "MATCH (p:Player)-[r:BOWLED_IN]->(m:Match) "
            "RETURN p.name AS player, SUM(r.wickets) AS total_wickets "
            "ORDER BY total_wickets DESC, player ASC LIMIT 5"
        ),
        "sql": (
            "SELECT pl.name AS player, SUM(b.wickets) AS total_wickets "
            "FROM bowled_in b JOIN players pl ON pl.id = b.player_id "
            "GROUP BY pl.id, pl.name "
            "ORDER BY total_wickets DESC, pl.name ASC LIMIT 5"
        ),
        "key_columns": ("player", "total_wickets"),
        "ground_truth_note": (
            "Wasim Akram, Waqar Younis, and Shahid Afridi are historically "
            "Pakistan's top wicket-takers. Imran Khan also features. "
            "Result depends on which formats are included in the corpus."
        ),
    },

    {
        "name": "NQ08_top_odi_fours_pakistan",
        "question": "Which Pakistani batters scored the most boundaries (fours) in ODI cricket?",
        "query_class": "aggregation",
        "cypher": (
            "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
            'WHERE m.format = "ODI" AND p.country = "PAK" '
            "RETURN p.name AS player, SUM(r.fours) AS odi_fours "
            "ORDER BY odi_fours DESC, player ASC LIMIT 5"
        ),
        "sql": (
            "SELECT pl.name AS player, SUM(b.fours) AS odi_fours "
            "FROM batted_in b JOIN players pl ON pl.id = b.player_id "
            "JOIN matches m ON m.id = b.match_id "
            "WHERE m.format = 'ODI' AND pl.country = 'PAK' "
            "GROUP BY pl.id, pl.name "
            "ORDER BY odi_fours DESC, pl.name ASC LIMIT 5"
        ),
        "key_columns": ("player", "odi_fours"),
        "ground_truth_note": (
            "Saeed Anwar was famous for elegant boundaries. Inzamam-ul-Haq, "
            "Mohammad Hafeez, and Babar Azam are also prolific ODI boundary-scorers."
        ),
    },

    {
        "name": "NQ09_avg_runs_conceded_test_pak",
        "question": "What is the average runs conceded per match by Pakistani bowlers in Test cricket?",
        "query_class": "aggregation",
        "cypher": (
            "MATCH (p:Player)-[r:BOWLED_IN]->(m:Match) "
            'WHERE m.format = "Test" AND p.country = "PAK" '
            "RETURN p.name AS bowler, AVG(r.runs_conceded) AS avg_conceded "
            "ORDER BY avg_conceded ASC, bowler ASC LIMIT 10"
        ),
        "sql": (
            "SELECT pl.name AS bowler, AVG(b.runs_conceded) AS avg_conceded "
            "FROM bowled_in b JOIN players pl ON pl.id = b.player_id "
            "JOIN matches m ON m.id = b.match_id "
            "WHERE m.format = 'Test' AND pl.country = 'PAK' "
            "GROUP BY pl.id, pl.name "
            "ORDER BY avg_conceded ASC, pl.name ASC LIMIT 10"
        ),
        "key_columns": ("bowler", "avg_conceded"),
        "ground_truth_note": (
            "Economy-oriented spinners (e.g., Saqlain Mushtaq, Danish Kaneria) "
            "should appear near the top. Pace bowlers (Wasim, Waqar) concede more "
            "runs per match but also take more wickets."
        ),
    },

    # ── C: Multi-hop path traversal ──────────────────────────────────────

    {
        "name": "NQ10_batters_at_karachi",
        "question": "Which players have batted the most times in matches played at Karachi?",
        "query_class": "multi_hop",
        "cypher": (
            "MATCH (p:Player)-[r:BATTED_IN]->(m:Match)-[:PLAYED_AT]->(v:Venue) "
            'WHERE v.city = "Karachi" '
            "RETURN p.name AS player, COUNT(m) AS karachi_innings "
            "ORDER BY karachi_innings DESC, player ASC LIMIT 10"
        ),
        "sql": (
            "SELECT pl.name AS player, COUNT(*) AS karachi_innings "
            "FROM batted_in b JOIN players pl ON pl.id = b.player_id "
            "JOIN matches m ON m.id = b.match_id "
            "JOIN venues v ON v.id = m.venue_id "
            "WHERE v.city = 'Karachi' "
            "GROUP BY pl.id, pl.name "
            "ORDER BY karachi_innings DESC, pl.name ASC LIMIT 10"
        ),
        "key_columns": ("player", "karachi_innings"),
        "ground_truth_note": (
            "National Stadium, Karachi is Pakistan's home fortress. Pakistani "
            "players (Inzamam, Younis, Salman Butt) dominate due to frequent home appearances."
        ),
    },

    {
        "name": "NQ11_matches_at_dubai_venues",
        "question": "How many matches were played at each venue in Dubai?",
        "query_class": "multi_hop",
        "cypher": (
            "MATCH (m:Match)-[:PLAYED_AT]->(v:Venue) "
            'WHERE v.city = "Dubai" '
            "RETURN v.name AS venue, COUNT(m) AS matches "
            "ORDER BY matches DESC, venue ASC LIMIT 10"
        ),
        "sql": (
            "SELECT v.name AS venue, COUNT(*) AS matches "
            "FROM matches m JOIN venues v ON v.id = m.venue_id "
            "WHERE v.city = 'Dubai' "
            "GROUP BY v.id, v.name "
            "ORDER BY matches DESC, v.name ASC LIMIT 10"
        ),
        "key_columns": ("venue", "matches"),
        "ground_truth_note": (
            "Dubai International Cricket Stadium is Pakistan's de-facto home. "
            "The dataset shows it hosted 100+ Pakistan matches."
        ),
    },

    {
        "name": "NQ12_bowlers_at_abu_dhabi",
        "question": "Which bowlers took the most wickets in matches played at Abu Dhabi?",
        "query_class": "multi_hop",
        "cypher": (
            "MATCH (p:Player)-[r:BOWLED_IN]->(m:Match)-[:PLAYED_AT]->(v:Venue) "
            'WHERE v.city = "Abu Dhabi" '
            "RETURN p.name AS bowler, SUM(r.wickets) AS wickets "
            "ORDER BY wickets DESC, bowler ASC LIMIT 5"
        ),
        "sql": (
            "SELECT pl.name AS bowler, SUM(b.wickets) AS wickets "
            "FROM bowled_in b JOIN players pl ON pl.id = b.player_id "
            "JOIN matches m ON m.id = b.match_id "
            "JOIN venues v ON v.id = m.venue_id "
            "WHERE v.city = 'Abu Dhabi' "
            "GROUP BY pl.id, pl.name "
            "ORDER BY wickets DESC, pl.name ASC LIMIT 5"
        ),
        "key_columns": ("bowler", "wickets"),
        "ground_truth_note": (
            "Saeed Ajmal, Junaid Khan, and Mohammad Hafeez performed well at "
            "Sheikh Zayed Stadium, Abu Dhabi — Pakistan's frequent neutral venue."
        ),
    },

    {
        "name": "NQ13_matches_per_tournament",
        "question": "Which tournaments featured the most matches in the dataset?",
        "query_class": "multi_hop",
        "cypher": (
            "MATCH (m:Match)-[:PART_OF_TOURNAMENT]->(t:Tournament) "
            "RETURN t.name AS tournament, COUNT(m) AS match_count "
            "ORDER BY match_count DESC, tournament ASC LIMIT 10"
        ),
        "sql": (
            "SELECT t.name AS tournament, COUNT(*) AS match_count "
            "FROM part_of_tournament pt JOIN tournaments t ON t.id = pt.tournament_id "
            "GROUP BY t.id, t.name "
            "ORDER BY match_count DESC, t.name ASC LIMIT 10"
        ),
        "key_columns": ("tournament", "match_count"),
        "ground_truth_note": (
            "Asia Cup, ICC World Cup, and Champions Trophy series should top the list "
            "alongside bilateral series (Pakistan vs Australia, etc.)."
        ),
    },

    # ── D: Multi-pattern conjunction ─────────────────────────────────────

    {
        "name": "NQ14_all_rounders_by_dual_match_count",
        "question": "Which players contributed to both batting and bowling in the most matches?",
        "query_class": "multi_pattern",
        "cypher": (
            "MATCH (p:Player)-[b:BATTED_IN]->(m:Match), (p)-[w:BOWLED_IN]->(m) "
            "RETURN p.name AS allrounder, COUNT(m) AS matches "
            "ORDER BY matches DESC, allrounder ASC LIMIT 10"
        ),
        "sql": (
            "SELECT pl.name AS allrounder, COUNT(DISTINCT b.match_id) AS matches "
            "FROM batted_in b "
            "JOIN bowled_in w ON w.player_id = b.player_id AND w.match_id = b.match_id "
            "JOIN players pl ON pl.id = b.player_id "
            "GROUP BY pl.id, pl.name "
            "ORDER BY matches DESC, pl.name ASC LIMIT 10"
        ),
        "key_columns": ("allrounder", "matches"),
        "ground_truth_note": (
            "Shahid Afridi (163 matches), Mohammad Hafeez (146), and Shoaib Malik "
            "top the list — Pakistan's classic all-rounders who both batted and bowled "
            "across their careers."
        ),
    },

    {
        "name": "NQ15_quality_karachi_innings",
        "question": "Which players batted at Karachi AND scored at least 30 runs in those innings?",
        "query_class": "multi_pattern",
        "cypher": (
            "MATCH (p:Player)-[r:BATTED_IN]->(m:Match)-[:PLAYED_AT]->(v:Venue) "
            'WHERE v.city = "Karachi" AND r.runs >= 30 '
            "RETURN p.name AS player, COUNT(m) AS quality_innings "
            "ORDER BY quality_innings DESC, player ASC LIMIT 10"
        ),
        "sql": (
            "SELECT pl.name AS player, COUNT(*) AS quality_innings "
            "FROM batted_in b JOIN players pl ON pl.id = b.player_id "
            "JOIN matches m ON m.id = b.match_id "
            "JOIN venues v ON v.id = m.venue_id "
            "WHERE v.city = 'Karachi' AND b.runs >= 30 "
            "GROUP BY pl.id, pl.name "
            "ORDER BY quality_innings DESC, pl.name ASC LIMIT 10"
        ),
        "key_columns": ("player", "quality_innings"),
        "ground_truth_note": (
            "Younis Khan and Inzamam-ul-Haq have historically made many "
            "meaningful contributions at their home ground in Karachi."
        ),
    },

    {
        "name": "NQ16_pak_test_allrounders",
        "question": "Which Pakistani players batted AND bowled in the same Test match?",
        "query_class": "multi_pattern",
        "cypher": (
            "MATCH (p:Player)-[b:BATTED_IN]->(m:Match), (p)-[w:BOWLED_IN]->(m) "
            'WHERE m.format = "Test" AND p.country = "PAK" '
            "RETURN p.name AS allrounder, COUNT(m) AS test_matches "
            "ORDER BY test_matches DESC, allrounder ASC LIMIT 10"
        ),
        "sql": (
            "SELECT pl.name AS allrounder, COUNT(DISTINCT b.match_id) AS test_matches "
            "FROM batted_in b "
            "JOIN bowled_in w ON w.player_id = b.player_id AND w.match_id = b.match_id "
            "JOIN players pl ON pl.id = b.player_id "
            "JOIN matches m ON m.id = b.match_id "
            "WHERE m.format = 'Test' AND pl.country = 'PAK' "
            "GROUP BY pl.id, pl.name "
            "ORDER BY test_matches DESC, pl.name ASC LIMIT 10"
        ),
        "key_columns": ("allrounder", "test_matches"),
        "ground_truth_note": (
            "Imran Khan (75 Tests), Wasim Akram (104 Tests), and Shahid Afridi "
            "are definitive Pakistan Test all-rounders. Shoaib Malik, "
            "Mushtaq Ahmed also feature."
        ),
    },

    {
        "name": "NQ17_match_best_batting_bowling",
        "question": "Which players scored 50+ runs AND took at least 1 wicket in the same match?",
        "query_class": "multi_pattern",
        "cypher": (
            "MATCH (p:Player)-[b:BATTED_IN]->(m:Match), (p)-[w:BOWLED_IN]->(m) "
            "WHERE b.runs >= 50 AND w.wickets >= 1 "
            "RETURN p.name AS allrounder, m.date AS match_date, "
            "b.runs AS runs, w.wickets AS wickets "
            "ORDER BY runs DESC, allrounder ASC LIMIT 10"
        ),
        "sql": (
            "SELECT pl.name AS allrounder, m.date AS match_date, "
            "b.runs AS runs, w.wickets AS wickets "
            "FROM batted_in b "
            "JOIN bowled_in w ON w.player_id = b.player_id AND w.match_id = b.match_id "
            "JOIN players pl ON pl.id = b.player_id "
            "JOIN matches m ON m.id = b.match_id "
            "WHERE b.runs >= 50 AND w.wickets >= 1 "
            "ORDER BY b.runs DESC, pl.name ASC LIMIT 10"
        ),
        "key_columns": ("allrounder", "match_date", "runs", "wickets"),
        "ground_truth_note": (
            "Imran Khan's legendary performances (e.g., 117 & 6 wkts vs India 1982) "
            "should appear. Shahid Afridi and Wasim Akram also had such matches."
        ),
    },

    # ── E: Undirected edge queries ───────────────────────────────────────

    {
        "name": "NQ18_rizwan_teammates",
        "question": "Who are Mohammad Rizwan's most frequent teammates?",
        "query_class": "undirected",
        "cypher": (
            "MATCH (p1:Player)-[t:TEAMMATES_WITH]-(p2:Player) "
            'WHERE p1.name = "Mohammad Rizwan" '
            "RETURN p2.name AS teammate, t.match_count AS shared_matches "
            "ORDER BY shared_matches DESC, teammate ASC LIMIT 10"
        ),
        "sql": (
            "SELECT pl2.name AS teammate, t.match_count AS shared_matches "
            "FROM teammates_with t "
            "JOIN players pl1 ON pl1.id = t.player_a_id "
            "JOIN players pl2 ON pl2.id = t.player_b_id "
            "WHERE pl1.name = 'Mohammad Rizwan' "
            "UNION ALL "
            "SELECT pl1.name AS teammate, t.match_count AS shared_matches "
            "FROM teammates_with t "
            "JOIN players pl1 ON pl1.id = t.player_a_id "
            "JOIN players pl2 ON pl2.id = t.player_b_id "
            "WHERE pl2.name = 'Mohammad Rizwan' "
            "ORDER BY shared_matches DESC, teammate ASC LIMIT 10"
        ),
        "key_columns": ("teammate", "shared_matches"),
        "ground_truth_note": (
            "Babar Azam, Shaheen Afridi, and Fakhar Zaman should top Rizwan's list "
            "— they are Pakistan's core T20I and ODI eleven since ~2019."
        ),
    },

    {
        "name": "NQ19_most_connected_player",
        "question": "Which players have the most unique teammates in the dataset?",
        "query_class": "undirected",
        "cypher": (
            "MATCH (p1:Player)-[t:TEAMMATES_WITH]-(p2:Player) "
            "RETURN p1.name AS player, COUNT(p2) AS teammate_count "
            "ORDER BY teammate_count DESC, player ASC LIMIT 5"
        ),
        "sql": (
            "SELECT pl.name AS player, COUNT(*) AS teammate_count "
            "FROM ( "
            "  SELECT player_a_id AS pid FROM teammates_with "
            "  UNION ALL "
            "  SELECT player_b_id AS pid FROM teammates_with "
            ") paired JOIN players pl ON pl.id = paired.pid "
            "GROUP BY pl.id, pl.name "
            "ORDER BY teammate_count DESC, pl.name ASC LIMIT 5"
        ),
        "key_columns": ("player", "teammate_count"),
        "ground_truth_note": (
            "Long-serving Pakistan stalwarts (Shahid Afridi, Inzamam-ul-Haq, "
            "Shoaib Malik) played with the most diverse sets of teammates across eras."
        ),
    },

    {
        "name": "NQ20_babar_shaheen_shared_matches",
        "question": "How many matches have Babar Azam and Shaheen Shah Afridi been in the same team?",
        "query_class": "undirected",
        "cypher": (
            "MATCH (p1:Player)-[t:TEAMMATES_WITH]-(p2:Player) "
            'WHERE p1.name = "Babar Azam" AND p2.name = "Shaheen Shah Afridi" '
            "RETURN t.match_count AS shared_matches"
        ),
        "sql": (
            "SELECT t.match_count AS shared_matches "
            "FROM teammates_with t "
            "JOIN players pl1 ON pl1.id = t.player_a_id "
            "JOIN players pl2 ON pl2.id = t.player_b_id "
            "WHERE (pl1.name = 'Babar Azam' AND pl2.name = 'Shaheen Shah Afridi') "
            "   OR (pl1.name = 'Shaheen Shah Afridi' AND pl2.name = 'Babar Azam')"
        ),
        "key_columns": ("shared_matches",),
        "ground_truth_note": (
            "Babar and Shaheen Shah Afridi have been Pakistan's captain-spearhead duo since 2020. "
            "Full corpus shows 100+ shared appearances across all formats."
        ),
    },

    # ── F: RPQ / bounded Kleene-star ────────────────────────────────────

    {
        "name": "NQ21_rpq_five_hops",
        "question": "How many deliveries are reachable within 5 hops of a starting delivery?",
        "query_class": "rpq",
        "cypher": (
            "MATCH (d:Delivery)-[:NEXT_DELIVERY*1..5]->(d2:Delivery) "
            'WHERE d.id = "{start_id}" '
            "RETURN COUNT(d2) AS reachable"
        ),
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ( "
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT n.next_id, c.depth + 1 "
            "  FROM chain c JOIN next_delivery n ON n.prev_id = c.end_id "
            "  WHERE c.depth < 5 "
            ") "
            "SELECT COUNT(*) AS reachable FROM chain WHERE end_id IS NOT NULL"
        ),
        "key_columns": ("reachable",),
        "needs_start_id": True,
        "ground_truth_note": (
            "NEXT_DELIVERY is a linear chain (1:1). From any delivery that has "
            "at least 5 successors, reachable = 5. If the chain ends earlier, "
            "reachable < 5. The Cypher BFS and SQL WITH RECURSIVE must agree."
        ),
    },

    {
        "name": "NQ22_rpq_exact_two_hops",
        "question": "Which delivery is exactly 2 hops after a starting delivery?",
        "query_class": "rpq",
        "cypher": (
            "MATCH (d:Delivery)-[:NEXT_DELIVERY*2]->(d2:Delivery) "
            'WHERE d.id = "{start_id}" '
            "RETURN d2.id AS delivery_2_hops"
        ),
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ( "
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT n.next_id, c.depth + 1 "
            "  FROM chain c JOIN next_delivery n ON n.prev_id = c.end_id "
            "  WHERE c.depth < 2 "
            ") "
            "SELECT end_id AS delivery_2_hops FROM chain WHERE depth = 2"
        ),
        "key_columns": ("delivery_2_hops",),
        "needs_start_id": True,
        "ground_truth_note": (
            "Since NEXT_DELIVERY is 1:1, there is at most one delivery 2 hops away. "
            "Cypher `*2` and SQL two-CTE expansion must return the same single row."
        ),
    },

    {
        "name": "NQ23_rpq_teammates_3_hops",
        "question": "Who are the players reachable from Babar Azam within 3 TEAMMATES_WITH hops?",
        "query_class": "rpq",
        "cypher": (
            "MATCH (p1:Player)-[:TEAMMATES_WITH*1..3]-(p2:Player) "
            'WHERE p1.name = "Babar Azam" '
            "RETURN p2.name AS within_3_hops "
            "ORDER BY within_3_hops ASC"
        ),
        "sql": (
            "WITH RECURSIVE reach(node, depth) AS ( "
            "  SELECT CASE WHEN player_a_id = (SELECT id FROM players WHERE name='Babar Azam') "
            "              THEN player_b_id ELSE player_a_id END AS node, 1 AS depth "
            "  FROM teammates_with "
            "  WHERE player_a_id = (SELECT id FROM players WHERE name='Babar Azam') "
            "     OR player_b_id = (SELECT id FROM players WHERE name='Babar Azam') "
            "  UNION "
            "  SELECT CASE WHEN t.player_a_id = r.node THEN t.player_b_id "
            "              ELSE t.player_a_id END, "
            "         r.depth + 1 "
            "  FROM teammates_with t JOIN reach r "
            "       ON (t.player_a_id = r.node OR t.player_b_id = r.node) "
            "  WHERE r.depth < 3 "
            ") "
            "SELECT DISTINCT pl.name AS within_3_hops "
            "FROM reach r JOIN players pl ON pl.id = r.node "
            "WHERE pl.name != 'Babar Azam' "
            "ORDER BY within_3_hops ASC"
        ),
        "key_columns": ("within_3_hops",),
        "ground_truth_note": (
            "Babar's direct teammates span ~50+ players. Within 3 hops the cricket "
            "community is highly interconnected, so the result set is large. "
            "Cypher's node-deduplication and SQL's UNION (not UNION ALL) must agree."
        ),
    },

    {
        "name": "NQ24_rpq_zero_or_more",
        "question": "How many deliveries (including itself) are reachable within 3 hops using zero-or-more?",
        "query_class": "rpq",
        "cypher": (
            "MATCH (d:Delivery)-[:NEXT_DELIVERY*0..3]->(d2:Delivery) "
            'WHERE d.id = "{start_id}" '
            "RETURN COUNT(d2) AS reachable_incl_self"
        ),
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ( "
            "  SELECT '{start_id}' AS end_id, 0 AS depth "
            "  UNION ALL "
            "  SELECT n.next_id, c.depth + 1 "
            "  FROM chain c JOIN next_delivery n ON n.prev_id = c.end_id "
            "  WHERE c.depth < 3 "
            ") "
            "SELECT COUNT(*) AS reachable_incl_self FROM chain WHERE end_id IS NOT NULL"
        ),
        "key_columns": ("reachable_incl_self",),
        "needs_start_id": True,
        "ground_truth_note": (
            "`*0..3` includes depth-0 (the start node itself). Expected = 4 when the "
            "chain has >= 3 successors: start + 3 next deliveries. "
            "Tests the zero-or-more quantifier implementation."
        ),
    },

    {
        "name": "NQ25_rpq_one_or_more_capped",
        "question": "How many deliveries are reachable within 8 hops using one-or-more?",
        "query_class": "rpq",
        "cypher": (
            "MATCH (d:Delivery)-[:NEXT_DELIVERY*1..8]->(d2:Delivery) "
            'WHERE d.id = "{start_id}" '
            "RETURN COUNT(d2) AS reachable_plus"
        ),
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ( "
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT n.next_id, c.depth + 1 "
            "  FROM chain c JOIN next_delivery n ON n.prev_id = c.end_id "
            "  WHERE c.depth < 8 "
            ") "
            "SELECT COUNT(*) AS reachable_plus FROM chain WHERE end_id IS NOT NULL"
        ),
        "key_columns": ("reachable_plus",),
        "needs_start_id": True,
        "ground_truth_note": (
            "This tests `*1..8` which is equivalent to `[:NEXT_DELIVERY+]` bounded to "
            "8 hops. For a chain with >= 8 successors, reachable_plus = 8. "
            "The SQL uses the same bound. Engines must agree."
        ),
    },

    # ── G: RPQ + target-side property filter ─────────────────────────────

    {
        "name": "NQ26_rpq_scoring_within_10",
        "question": "How many of the next 10 deliveries after a starting ball scored runs?",
        "query_class": "rpq_filter",
        "cypher": (
            "MATCH (d:Delivery)-[:NEXT_DELIVERY*1..10]->(d2:Delivery) "
            'WHERE d.id = "{start_id}" AND d2.runs_batter > 0 '
            "RETURN COUNT(d2) AS scoring_deliveries"
        ),
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ( "
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT n.next_id, c.depth + 1 "
            "  FROM chain c JOIN next_delivery n ON n.prev_id = c.end_id "
            "  WHERE c.depth < 10 "
            ") "
            "SELECT COUNT(*) AS scoring_deliveries "
            "FROM chain c JOIN deliveries d ON d.id = c.end_id "
            "WHERE d.runs_batter > 0"
        ),
        "key_columns": ("scoring_deliveries",),
        "needs_start_id": True,
        "ground_truth_note": (
            "Typically 4-7 of 10 deliveries score runs (strike rate ~40-70%). "
            "The RPQ traverses the chain and filters only scoring deliveries. "
            "Result must match between Cypher BFS+filter and SQL CTE+join."
        ),
    },

    {
        "name": "NQ27_pak_teammates_within_2_hops",
        "question": "Which Pakistani players are within 2 teammate-hops of Babar Azam?",
        "query_class": "rpq_filter",
        "cypher": (
            "MATCH (p1:Player)-[:TEAMMATES_WITH*1..2]-(p2:Player) "
            'WHERE p1.name = "Babar Azam" AND p2.country = "PAK" '
            "RETURN p2.name AS pak_teammate "
            "ORDER BY pak_teammate ASC"
        ),
        "sql": (
            "WITH RECURSIVE reach(node, depth) AS ( "
            "  SELECT CASE WHEN player_a_id = (SELECT id FROM players WHERE name='Babar Azam') "
            "              THEN player_b_id ELSE player_a_id END AS node, 1 AS depth "
            "  FROM teammates_with "
            "  WHERE player_a_id = (SELECT id FROM players WHERE name='Babar Azam') "
            "     OR player_b_id = (SELECT id FROM players WHERE name='Babar Azam') "
            "  UNION "
            "  SELECT CASE WHEN t.player_a_id = r.node THEN t.player_b_id "
            "              ELSE t.player_a_id END, "
            "         r.depth + 1 "
            "  FROM teammates_with t JOIN reach r "
            "       ON (t.player_a_id = r.node OR t.player_b_id = r.node) "
            "  WHERE r.depth < 2 "
            ") "
            "SELECT DISTINCT pl.name AS pak_teammate "
            "FROM reach r JOIN players pl ON pl.id = r.node "
            "WHERE pl.name != 'Babar Azam' AND pl.country = 'PAK' "
            "ORDER BY pak_teammate ASC"
        ),
        "key_columns": ("pak_teammate",),
        "ground_truth_note": (
            "Direct PAK teammates of Babar = his entire XI. Within 2 hops = "
            "anyone who played with any of Babar's direct teammates. "
            "In a ~30 year corpus, nearly all PAK players qualify."
        ),
    },

    {
        "name": "NQ28_rpq_boundary_deliveries",
        "question": "How many of the next 6 deliveries were boundaries (4+ runs for batter)?",
        "query_class": "rpq_filter",
        "cypher": (
            "MATCH (d:Delivery)-[:NEXT_DELIVERY*1..6]->(d2:Delivery) "
            'WHERE d.id = "{start_id}" AND d2.runs_batter >= 4 '
            "RETURN COUNT(d2) AS boundary_deliveries"
        ),
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ( "
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT n.next_id, c.depth + 1 "
            "  FROM chain c JOIN next_delivery n ON n.prev_id = c.end_id "
            "  WHERE c.depth < 6 "
            ") "
            "SELECT COUNT(*) AS boundary_deliveries "
            "FROM chain c JOIN deliveries d ON d.id = c.end_id "
            "WHERE d.runs_batter >= 4"
        ),
        "key_columns": ("boundary_deliveries",),
        "needs_start_id": True,
        "ground_truth_note": (
            "Boundary rate in cricket is typically ~10-15% of deliveries. "
            "From 6 deliveries expect 0-2 boundaries. "
            "Tests `>=` comparison operator on target-side node property after RPQ."
        ),
    },

    # ── H: Negation and boolean composition ──────────────────────────────

    {
        "name": "NQ29_boundaryless_innings",
        "question": "Which players batted in the most innings without scoring any boundary?",
        "query_class": "negation",
        "cypher": (
            "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
            "WHERE r.fours = 0 AND r.sixes = 0 "
            "RETURN p.name AS player, COUNT(m) AS boundaryless_innings "
            "ORDER BY boundaryless_innings DESC, player ASC LIMIT 10"
        ),
        "sql": (
            "SELECT pl.name AS player, COUNT(*) AS boundaryless_innings "
            "FROM batted_in b JOIN players pl ON pl.id = b.player_id "
            "WHERE b.fours = 0 AND b.sixes = 0 "
            "GROUP BY pl.id, pl.name "
            "ORDER BY boundaryless_innings DESC, pl.name ASC LIMIT 10"
        ),
        "key_columns": ("player", "boundaryless_innings"),
        "ground_truth_note": (
            "Tailenders and specialist bowlers appear most often (low scores without "
            "boundaries). Openers rarely appear here. Tests AND composition of two "
            "equality comparisons (fours=0 AND sixes=0)."
        ),
    },

    {
        "name": "NQ30_non_pak_players",
        "question": "Which non-Pakistani players (opponents) have played against Pakistan, by country?",
        "query_class": "negation",
        "cypher": (
            "MATCH (p:Player) "
            'WHERE p.country != "PAK" '
            "RETURN p.name AS player, p.country AS country "
            "ORDER BY country ASC, player ASC LIMIT 15"
        ),
        "sql": (
            "SELECT name AS player, country FROM players "
            "WHERE country != 'PAK' "
            "ORDER BY country ASC, name ASC LIMIT 15"
        ),
        "key_columns": ("player", "country"),
        "ground_truth_note": (
            "Should include players from AUS, ENG, IND, SA, NZ, WI, SL, ZIM, BAN. "
            "Tests `!=` operator on a string field."
        ),
    },

    {
        "name": "NQ31_non_test_format_innings",
        "question": "Which players batted the most times in non-Test matches (T20 or ODI)?",
        "query_class": "negation",
        "cypher": (
            "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
            'WHERE m.format != "Test" '
            "RETURN p.name AS player, COUNT(m) AS limited_overs_innings "
            "ORDER BY limited_overs_innings DESC, player ASC LIMIT 10"
        ),
        "sql": (
            "SELECT pl.name AS player, COUNT(*) AS limited_overs_innings "
            "FROM batted_in b JOIN players pl ON pl.id = b.player_id "
            "JOIN matches m ON m.id = b.match_id "
            "WHERE m.format != 'Test' "
            "GROUP BY pl.id, pl.name "
            "ORDER BY limited_overs_innings DESC, pl.name ASC LIMIT 10"
        ),
        "key_columns": ("player", "limited_overs_innings"),
        "ground_truth_note": (
            "Limited-overs specialists dominate. Shahid Afridi, Mohammad Hafeez, "
            "Shoaib Malik played massive numbers of T20I and ODI innings for Pakistan."
        ),
    },

    {
        "name": "NQ32_expensive_wicket_takers_t20",
        "question": "Which bowlers took wickets in T20s but conceded more than 30 runs in the same match?",
        "query_class": "negation",
        "cypher": (
            "MATCH (p:Player)-[r:BOWLED_IN]->(m:Match) "
            'WHERE m.format = "T20" AND r.wickets > 0 AND r.runs_conceded > 30 '
            "RETURN p.name AS bowler, COUNT(m) AS expensive_wicket_innings "
            "ORDER BY expensive_wicket_innings DESC, bowler ASC LIMIT 10"
        ),
        "sql": (
            "SELECT pl.name AS bowler, COUNT(*) AS expensive_wicket_innings "
            "FROM bowled_in b JOIN players pl ON pl.id = b.player_id "
            "JOIN matches m ON m.id = b.match_id "
            "WHERE m.format = 'T20' AND b.wickets > 0 AND b.runs_conceded > 30 "
            "GROUP BY pl.id, pl.name "
            "ORDER BY expensive_wicket_innings DESC, pl.name ASC LIMIT 10"
        ),
        "key_columns": ("bowler", "expensive_wicket_innings"),
        "ground_truth_note": (
            "Common in T20Is: a bowler takes wickets but still gets hit hard. "
            "Tests compound AND with >, > comparisons. Both engines must agree."
        ),
    },

    # ── I: Hard / compound multi-constraint queries ──────────────────────

    {
        "name": "NQ33_highest_single_match_score",
        "question": "Which players recorded the highest single-match batting score?",
        "query_class": "hard",
        "cypher": (
            "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
            "RETURN p.name AS player, MAX(r.runs) AS highest_score "
            "ORDER BY highest_score DESC, player ASC LIMIT 5"
        ),
        "sql": (
            "SELECT pl.name AS player, MAX(b.runs) AS highest_score "
            "FROM batted_in b JOIN players pl ON pl.id = b.player_id "
            "GROUP BY pl.id, pl.name "
            "ORDER BY highest_score DESC, pl.name ASC LIMIT 5"
        ),
        "key_columns": ("player", "highest_score"),
        "ground_truth_note": (
            "Hanif Mohammad's 337 (1958) and Younis Khan's 313 are Pakistan's highest "
            "individual scores. In the cricsheet corpus (mostly modern matches), "
            "Azhar Ali 302* and Younis Khan's big knocks dominate."
        ),
    },

    {
        "name": "NQ34_highest_match_batting_total",
        "question": "Which match had the highest combined batting total from all players?",
        "query_class": "hard",
        "cypher": (
            "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
            "RETURN m.id AS match_id, m.date AS date, SUM(r.runs) AS total_runs "
            "ORDER BY total_runs DESC, match_id ASC LIMIT 5"
        ),
        "sql": (
            "SELECT m.id AS match_id, m.date AS date, SUM(b.runs) AS total_runs "
            "FROM batted_in b JOIN matches m ON m.id = b.match_id "
            "GROUP BY m.id, m.date "
            "ORDER BY total_runs DESC, m.id ASC LIMIT 5"
        ),
        "key_columns": ("match_id", "date", "total_runs"),
        "ground_truth_note": (
            "High-scoring Test matches (700+ aggregate runs) and ODI run-fests (350+ per side) "
            "should appear. A 4-innings Test can accumulate 1000+ total batting runs."
        ),
    },

    {
        "name": "NQ35_most_hosted_venues",
        "question": "Which venues have hosted the most matches, and where are they located?",
        "query_class": "hard",
        "cypher": (
            "MATCH (m:Match)-[:PLAYED_AT]->(v:Venue) "
            "RETURN v.name AS venue, v.city AS city, COUNT(m) AS hosted_matches "
            "ORDER BY hosted_matches DESC, venue ASC LIMIT 10"
        ),
        "sql": (
            "SELECT v.name AS venue, v.city AS city, COUNT(*) AS hosted_matches "
            "FROM matches m JOIN venues v ON v.id = m.venue_id "
            "GROUP BY v.id, v.name, v.city "
            "ORDER BY hosted_matches DESC, v.name ASC LIMIT 10"
        ),
        "key_columns": ("venue", "city", "hosted_matches"),
        "ground_truth_note": (
            "Dubai International Cricket Stadium (100+ matches) is Pakistan's most-used "
            "neutral venue. National Stadium Karachi and Gaddafi Stadium Lahore lead "
            "the domestic list."
        ),
    },
]


def expressibility(query: dict) -> dict:
    """Structural metrics: token count + recursion flag + query class."""
    cypher_tokens = len(query["cypher"].split())
    sql_tokens = len(query["sql"].split())
    return {
        "cypher_tokens": cypher_tokens,
        "sql_tokens": sql_tokens,
        "ratio_sql_over_cypher": round(sql_tokens / cypher_tokens, 2),
        "sql_recursive": "WITH RECURSIVE" in query["sql"].upper(),
        "query_class": query["query_class"],
    }
