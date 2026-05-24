"""100-query NL benchmark suite for the Cricket Knowledge Graph.

Each entry has:
  - question       : natural-language question a cricket analyst would ask
  - query_class    : one of the 9 classes below
  - sql            : SQL equivalent — used ONLY as a hidden ground-truth oracle
                     (never shown to the translation model)
  - key_columns    : columns to extract from both GQL and SQL results for comparison
  - ground_truth_note : human-readable note about the expected answer

Query classes (A–I):
  A  simple_lookup      — single node scan, count or list          (10)
  B  aggregation        — single edge + SUM/AVG/MIN/MAX            (12)
  C  multi_hop          — 2+ edges in sequence                     (12)
  D  multi_pattern      — multiple comma-separated patterns        (12)
  E  undirected         — TEAMMATES_WITH undirected traversal      (10)
  F  rpq                — bounded Kleene-star on NEXT_DELIVERY     (10)
  G  rpq_filter         — RPQ + target-side property filter        (10)
  H  negation           — NOT / != / boolean composition           (12)
  I  hard               — compound multi-constraint                (12)

Entries with `needs_start_id: True` have a `{start_id}` placeholder in `sql`;
the harness fills it with a real Delivery id at runtime.  The translation
model receives the question with the start id already substituted.
"""

from __future__ import annotations

SUITE: list[dict] = [

    # ── A: Simple property lookup / count ───────────────────────────────────

    {
        "name": "SQ_A01_total_matches",
        "question": "How many matches are in the dataset?",
        "query_class": "simple_lookup",
        "sql": "SELECT COUNT(*) AS total_matches FROM matches",
        "key_columns": ("total_matches",),
        "ground_truth_note": "Full corpus: 1,123. Fixture: 5.",
    },
    {
        "name": "SQ_A02_total_players",
        "question": "How many unique players are in the dataset?",
        "query_class": "simple_lookup",
        "sql": "SELECT COUNT(*) AS total_players FROM players",
        "key_columns": ("total_players",),
        "ground_truth_note": "Full corpus: 1,920. Fixture: 16.",
    },
    {
        "name": "SQ_A03_total_venues",
        "question": "How many venues are recorded in the dataset?",
        "query_class": "simple_lookup",
        "sql": "SELECT COUNT(*) AS total_venues FROM venues",
        "key_columns": ("total_venues",),
        "ground_truth_note": "Full corpus: 210. Fixture: 5.",
    },
    {
        "name": "SQ_A04_test_match_count",
        "question": "How many Test matches are in the dataset?",
        "query_class": "simple_lookup",
        "sql": "SELECT COUNT(*) AS test_matches FROM matches WHERE format = 'Test'",
        "key_columns": ("test_matches",),
        "ground_truth_note": "Full corpus: 448. Fixture: 1.",
    },
    {
        "name": "SQ_A05_t20_match_count",
        "question": "How many T20 matches are in the dataset?",
        "query_class": "simple_lookup",
        "sql": "SELECT COUNT(*) AS t20_matches FROM matches WHERE format = 'T20'",
        "key_columns": ("t20_matches",),
        "ground_truth_note": "Full corpus: ~500. Fixture: 4.",
    },
    {
        "name": "SQ_A06_odi_match_count",
        "question": "How many ODI matches are in the dataset?",
        "query_class": "simple_lookup",
        "sql": "SELECT COUNT(*) AS odi_matches FROM matches WHERE format = 'ODI'",
        "key_columns": ("odi_matches",),
        "ground_truth_note": "Full corpus: ~175. Fixture: 0.",
    },
    {
        "name": "SQ_A07_pak_player_count",
        "question": "How many Pakistani players are in the dataset?",
        "query_class": "simple_lookup",
        "sql": "SELECT COUNT(*) AS pak_players FROM players WHERE country = 'PAK'",
        "key_columns": ("pak_players",),
        "ground_truth_note": "Full corpus: ~250. Fixture: 5.",
    },
    {
        "name": "SQ_A08_total_tournaments",
        "question": "How many tournaments are recorded in the dataset?",
        "query_class": "simple_lookup",
        "sql": "SELECT COUNT(*) AS total_tournaments FROM tournaments",
        "key_columns": ("total_tournaments",),
        "ground_truth_note": "Full corpus: 155. Fixture: 1 (Asia Cup 2024).",
    },
    {
        "name": "SQ_A09_matches_by_format",
        "question": "How many matches of each format are there, ordered by count descending?",
        "query_class": "simple_lookup",
        "sql": (
            "SELECT format, COUNT(*) AS match_count "
            "FROM matches GROUP BY format ORDER BY match_count DESC"
        ),
        "key_columns": ("format", "match_count"),
        "ground_truth_note": "Groups all matches by format string.",
    },
    {
        "name": "SQ_A10_matches_by_season",
        "question": "Which 10 seasons have the most matches, ordered by match count descending?",
        "query_class": "simple_lookup",
        "sql": (
            "SELECT season, COUNT(*) AS match_count "
            "FROM matches GROUP BY season ORDER BY match_count DESC LIMIT 10"
        ),
        "key_columns": ("season", "match_count"),
        "ground_truth_note": "Top 10 seasons by match count.",
    },

    # ── B: Single-edge aggregation ───────────────────────────────────────────

    {
        "name": "SQ_B01_top_run_scorers",
        "question": "Who are the top 10 run scorers across all matches, ordered by total runs descending?",
        "query_class": "aggregation",
        "sql": (
            "SELECT p.name AS name, SUM(bi.runs) AS total_runs "
            "FROM players p JOIN batted_in bi ON bi.player_id = p.id "
            "GROUP BY p.id, p.name ORDER BY total_runs DESC LIMIT 10"
        ),
        "key_columns": ("name", "total_runs"),
        "ground_truth_note": "Aggregates all BATTED_IN edges. Fixture: Babar Azam leads with 31.",
    },
    {
        "name": "SQ_B02_top_wicket_takers",
        "question": "Who are the top 10 wicket takers across all matches, ordered by total wickets descending?",
        "query_class": "aggregation",
        "sql": (
            "SELECT p.name AS name, SUM(bw.wickets) AS total_wickets "
            "FROM players p JOIN bowled_in bw ON bw.player_id = p.id "
            "GROUP BY p.id, p.name ORDER BY total_wickets DESC LIMIT 10"
        ),
        "key_columns": ("name", "total_wickets"),
        "ground_truth_note": "Fixture: Naseem Shah leads with 2 wickets.",
    },
    {
        "name": "SQ_B03_pak_test_run_scorers",
        "question": "Which Pakistani players have scored the most runs in Test matches? Show the top 10 ordered by runs descending.",
        "query_class": "aggregation",
        "sql": (
            "SELECT p.name AS name, SUM(bi.runs) AS test_runs "
            "FROM players p "
            "JOIN batted_in bi ON bi.player_id = p.id "
            "JOIN matches m ON m.id = bi.match_id "
            "WHERE p.country = 'PAK' AND m.format = 'Test' "
            "GROUP BY p.id, p.name ORDER BY test_runs DESC LIMIT 10"
        ),
        "key_columns": ("name", "test_runs"),
        "ground_truth_note": "PAK batters in Test format only.",
    },
    {
        "name": "SQ_B04_most_sixes",
        "question": "Who has hit the most sixes across all matches? Show the top 10 ordered by total sixes descending.",
        "query_class": "aggregation",
        "sql": (
            "SELECT p.name AS name, SUM(bi.sixes) AS total_sixes "
            "FROM players p JOIN batted_in bi ON bi.player_id = p.id "
            "GROUP BY p.id, p.name ORDER BY total_sixes DESC LIMIT 10"
        ),
        "key_columns": ("name", "total_sixes"),
        "ground_truth_note": "Counts sixes from BATTED_IN edge property.",
    },
    {
        "name": "SQ_B05_most_fours",
        "question": "Who has hit the most fours across all matches? Show the top 10 ordered by total fours descending.",
        "query_class": "aggregation",
        "sql": (
            "SELECT p.name AS name, SUM(bi.fours) AS total_fours "
            "FROM players p JOIN batted_in bi ON bi.player_id = p.id "
            "GROUP BY p.id, p.name ORDER BY total_fours DESC LIMIT 10"
        ),
        "key_columns": ("name", "total_fours"),
        "ground_truth_note": "Counts boundary fours from BATTED_IN edge property.",
    },
    {
        "name": "SQ_B06_pak_t20_avg_runs",
        "question": "What is the average runs per innings for each Pakistani player in T20 matches? Show the top 10 ordered by average descending.",
        "query_class": "aggregation",
        "sql": (
            "SELECT p.name AS name, AVG(bi.runs) AS avg_runs "
            "FROM players p "
            "JOIN batted_in bi ON bi.player_id = p.id "
            "JOIN matches m ON m.id = bi.match_id "
            "WHERE p.country = 'PAK' AND m.format = 'T20' "
            "GROUP BY p.id, p.name ORDER BY avg_runs DESC LIMIT 10"
        ),
        "key_columns": ("name", "avg_runs"),
        "ground_truth_note": "AVG over all T20 innings per PAK player.",
    },
    {
        "name": "SQ_B07_most_expensive_bowlers",
        "question": "Which bowlers conceded the most runs in total across all matches? Show the top 10.",
        "query_class": "aggregation",
        "sql": (
            "SELECT p.name AS name, SUM(bw.runs_conceded) AS total_conceded "
            "FROM players p JOIN bowled_in bw ON bw.player_id = p.id "
            "GROUP BY p.id, p.name ORDER BY total_conceded DESC LIMIT 10"
        ),
        "key_columns": ("name", "total_conceded"),
        "ground_truth_note": "SUM of runs_conceded across all bowling innings.",
    },
    {
        "name": "SQ_B08_most_test_maidens",
        "question": "Which bowlers bowled the most maiden overs in Test matches? Show the top 10.",
        "query_class": "aggregation",
        "sql": (
            "SELECT p.name AS name, SUM(bw.maidens) AS total_maidens "
            "FROM players p "
            "JOIN bowled_in bw ON bw.player_id = p.id "
            "JOIN matches m ON m.id = bw.match_id "
            "WHERE m.format = 'Test' "
            "GROUP BY p.id, p.name ORDER BY total_maidens DESC LIMIT 10"
        ),
        "key_columns": ("name", "total_maidens"),
        "ground_truth_note": "Maiden overs bowled in Test format only.",
    },
    {
        "name": "SQ_B09_pak_t20_wickets",
        "question": "Which Pakistani bowlers took the most wickets in T20 matches? Show the top 10.",
        "query_class": "aggregation",
        "sql": (
            "SELECT p.name AS name, SUM(bw.wickets) AS t20_wickets "
            "FROM players p "
            "JOIN bowled_in bw ON bw.player_id = p.id "
            "JOIN matches m ON m.id = bw.match_id "
            "WHERE p.country = 'PAK' AND m.format = 'T20' "
            "GROUP BY p.id, p.name ORDER BY t20_wickets DESC LIMIT 10"
        ),
        "key_columns": ("name", "t20_wickets"),
        "ground_truth_note": "PAK bowlers in T20 format only.",
    },
    {
        "name": "SQ_B10_most_matches_batted",
        "question": "Which players batted in the most matches? Show the top 10 ordered by match count descending.",
        "query_class": "aggregation",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS matches_batted "
            "FROM players p JOIN batted_in bi ON bi.player_id = p.id "
            "GROUP BY p.id, p.name ORDER BY matches_batted DESC LIMIT 10"
        ),
        "key_columns": ("name", "matches_batted"),
        "ground_truth_note": "Count of BATTED_IN edges per player.",
    },
    {
        "name": "SQ_B11_pak_avg_balls_faced",
        "question": "What is the average number of balls faced per innings for each Pakistani player? Show the top 10.",
        "query_class": "aggregation",
        "sql": (
            "SELECT p.name AS name, AVG(bi.balls_faced) AS avg_balls "
            "FROM players p JOIN batted_in bi ON bi.player_id = p.id "
            "WHERE p.country = 'PAK' "
            "GROUP BY p.id, p.name ORDER BY avg_balls DESC LIMIT 10"
        ),
        "key_columns": ("name", "avg_balls"),
        "ground_truth_note": "Average balls faced per batting innings, PAK only.",
    },
    {
        "name": "SQ_B12_pak_test_min_runs",
        "question": "What is the lowest score each Pakistani player has made in a single Test innings? Show 10 players ordered by lowest score ascending.",
        "query_class": "aggregation",
        "sql": (
            "SELECT p.name AS name, MIN(bi.runs) AS min_runs "
            "FROM players p "
            "JOIN batted_in bi ON bi.player_id = p.id "
            "JOIN matches m ON m.id = bi.match_id "
            "WHERE p.country = 'PAK' AND m.format = 'Test' "
            "GROUP BY p.id, p.name ORDER BY min_runs ASC LIMIT 10"
        ),
        "key_columns": ("name", "min_runs"),
        "ground_truth_note": "MIN runs in a single Test innings per PAK player.",
    },

    # ── C: Multi-hop path traversal ─────────────────────────────────────────

    {
        "name": "SQ_C01_batters_at_karachi",
        "question": "Which players batted at Karachi, and in how many matches there? Order by match count descending.",
        "query_class": "multi_hop",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS matches_at_venue "
            "FROM players p "
            "JOIN batted_in bi ON bi.player_id = p.id "
            "JOIN matches m ON m.id = bi.match_id "
            "JOIN played_at pa ON pa.match_id = m.id "
            "JOIN venues v ON v.id = pa.venue_id "
            "WHERE v.city = 'Karachi' "
            "GROUP BY p.id, p.name ORDER BY matches_at_venue DESC"
        ),
        "key_columns": ("name", "matches_at_venue"),
        "ground_truth_note": "2-hop: Player→Match→Venue, filtered to Karachi.",
    },
    {
        "name": "SQ_C02_bowlers_at_dubai",
        "question": "Which bowlers took the most wickets at Dubai venues? Show the top 10 ordered by wickets descending.",
        "query_class": "multi_hop",
        "sql": (
            "SELECT p.name AS name, SUM(bw.wickets) AS dubai_wickets "
            "FROM players p "
            "JOIN bowled_in bw ON bw.player_id = p.id "
            "JOIN matches m ON m.id = bw.match_id "
            "JOIN played_at pa ON pa.match_id = m.id "
            "JOIN venues v ON v.id = pa.venue_id "
            "WHERE v.city = 'Dubai' "
            "GROUP BY p.id, p.name ORDER BY dubai_wickets DESC LIMIT 10"
        ),
        "key_columns": ("name", "dubai_wickets"),
        "ground_truth_note": "2-hop via BOWLED_IN→PLAYED_AT, filtered to Dubai.",
    },
    {
        "name": "SQ_C03_captains_at_karachi",
        "question": "Which players captained a team at Karachi and how many times did they captain there?",
        "query_class": "multi_hop",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS times_captained "
            "FROM players p "
            "JOIN captained ca ON ca.player_id = p.id "
            "JOIN matches m ON m.id = ca.match_id "
            "JOIN played_at pa ON pa.match_id = m.id "
            "JOIN venues v ON v.id = pa.venue_id "
            "WHERE v.city = 'Karachi' "
            "GROUP BY p.id, p.name ORDER BY times_captained DESC"
        ),
        "key_columns": ("name", "times_captained"),
        "ground_truth_note": "2-hop: Player→Match→Venue via CAPTAINED and PLAYED_AT.",
    },
    {
        "name": "SQ_C04_batters_in_tournaments",
        "question": "Which players batted in tournament matches and in how many? Show top 10 ordered by match count descending.",
        "query_class": "multi_hop",
        "sql": (
            "SELECT p.name AS name, t.name AS tournament, COUNT(*) AS matches_in_tournament "
            "FROM players p "
            "JOIN batted_in bi ON bi.player_id = p.id "
            "JOIN matches m ON m.id = bi.match_id "
            "JOIN part_of_tournament pot ON pot.match_id = m.id "
            "JOIN tournaments t ON t.id = pot.tournament_id "
            "GROUP BY p.id, p.name, t.id, t.name "
            "ORDER BY matches_in_tournament DESC LIMIT 10"
        ),
        "key_columns": ("name", "tournament", "matches_in_tournament"),
        "ground_truth_note": "2-hop: Player→Match→Tournament.",
    },
    {
        "name": "SQ_C05_runs_per_venue",
        "question": "How many total runs were scored at each venue? Order by total runs descending.",
        "query_class": "multi_hop",
        "sql": (
            "SELECT v.name AS venue, SUM(bi.runs) AS total_runs "
            "FROM batted_in bi "
            "JOIN matches m ON m.id = bi.match_id "
            "JOIN played_at pa ON pa.match_id = m.id "
            "JOIN venues v ON v.id = pa.venue_id "
            "GROUP BY v.id, v.name ORDER BY total_runs DESC"
        ),
        "key_columns": ("venue", "total_runs"),
        "ground_truth_note": "SUM of all batting runs grouped by venue.",
    },
    {
        "name": "SQ_C06_wickets_per_venue",
        "question": "How many total wickets were taken at each venue? Order by total wickets descending.",
        "query_class": "multi_hop",
        "sql": (
            "SELECT v.name AS venue, SUM(bw.wickets) AS total_wickets "
            "FROM bowled_in bw "
            "JOIN matches m ON m.id = bw.match_id "
            "JOIN played_at pa ON pa.match_id = m.id "
            "JOIN venues v ON v.id = pa.venue_id "
            "GROUP BY v.id, v.name ORDER BY total_wickets DESC"
        ),
        "key_columns": ("venue", "total_wickets"),
        "ground_truth_note": "SUM of wickets taken grouped by venue.",
    },
    {
        "name": "SQ_C07_pak_batting_innings_per_venue",
        "question": "How many batting innings did Pakistani players have at each venue? Order by innings count descending.",
        "query_class": "multi_hop",
        "sql": (
            "SELECT v.name AS venue, COUNT(*) AS pak_batting_innings "
            "FROM players p "
            "JOIN batted_in bi ON bi.player_id = p.id "
            "JOIN matches m ON m.id = bi.match_id "
            "JOIN played_at pa ON pa.match_id = m.id "
            "JOIN venues v ON v.id = pa.venue_id "
            "WHERE p.country = 'PAK' "
            "GROUP BY v.id, v.name ORDER BY pak_batting_innings DESC"
        ),
        "key_columns": ("venue", "pak_batting_innings"),
        "ground_truth_note": "Player-match pairs (not distinct players) per venue, PAK only.",
    },
    {
        "name": "SQ_C08_t20_sixes_per_venue",
        "question": "How many sixes were hit at each venue in T20 matches? Order by total sixes descending.",
        "query_class": "multi_hop",
        "sql": (
            "SELECT v.name AS venue, SUM(bi.sixes) AS total_sixes "
            "FROM batted_in bi "
            "JOIN matches m ON m.id = bi.match_id "
            "JOIN played_at pa ON pa.match_id = m.id "
            "JOIN venues v ON v.id = pa.venue_id "
            "WHERE m.format = 'T20' "
            "GROUP BY v.id, v.name ORDER BY total_sixes DESC"
        ),
        "key_columns": ("venue", "total_sixes"),
        "ground_truth_note": "T20 sixes grouped by venue.",
    },
    {
        "name": "SQ_C09_pak_wickets_per_tournament",
        "question": "How many wickets did Pakistani bowlers take in each tournament? Order by wickets descending.",
        "query_class": "multi_hop",
        "sql": (
            "SELECT t.name AS tournament, SUM(bw.wickets) AS pak_wickets "
            "FROM players p "
            "JOIN bowled_in bw ON bw.player_id = p.id "
            "JOIN matches m ON m.id = bw.match_id "
            "JOIN part_of_tournament pot ON pot.match_id = m.id "
            "JOIN tournaments t ON t.id = pot.tournament_id "
            "WHERE p.country = 'PAK' "
            "GROUP BY t.id, t.name ORDER BY pak_wickets DESC"
        ),
        "key_columns": ("tournament", "pak_wickets"),
        "ground_truth_note": "PAK bowling wickets grouped by tournament.",
    },
    {
        "name": "SQ_C10_runs_at_lahore",
        "question": "How many runs did each player score at Lahore? Order by runs descending.",
        "query_class": "multi_hop",
        "sql": (
            "SELECT p.name AS name, SUM(bi.runs) AS lahore_runs "
            "FROM players p "
            "JOIN batted_in bi ON bi.player_id = p.id "
            "JOIN matches m ON m.id = bi.match_id "
            "JOIN played_at pa ON pa.match_id = m.id "
            "JOIN venues v ON v.id = pa.venue_id "
            "WHERE v.city = 'Lahore' "
            "GROUP BY p.id, p.name ORDER BY lahore_runs DESC"
        ),
        "key_columns": ("name", "lahore_runs"),
        "ground_truth_note": "2-hop to venue, filtered to Lahore.",
    },
    {
        "name": "SQ_C11_test_wickets_outside_karachi",
        "question": "Which bowlers took the most Test wickets at venues outside Karachi? Show the top 10.",
        "query_class": "multi_hop",
        "sql": (
            "SELECT p.name AS name, SUM(bw.wickets) AS wickets "
            "FROM players p "
            "JOIN bowled_in bw ON bw.player_id = p.id "
            "JOIN matches m ON m.id = bw.match_id "
            "JOIN played_at pa ON pa.match_id = m.id "
            "JOIN venues v ON v.id = pa.venue_id "
            "WHERE m.format = 'Test' AND v.city != 'Karachi' "
            "GROUP BY p.id, p.name ORDER BY wickets DESC LIMIT 10"
        ),
        "key_columns": ("name", "wickets"),
        "ground_truth_note": "Test wickets at non-Karachi venues.",
    },
    {
        "name": "SQ_C12_birmingham_batting_innings",
        "question": "How many batting innings occurred at Birmingham venues?",
        "query_class": "multi_hop",
        "sql": (
            "SELECT v.name AS venue, COUNT(*) AS batting_innings "
            "FROM batted_in bi "
            "JOIN matches m ON m.id = bi.match_id "
            "JOIN played_at pa ON pa.match_id = m.id "
            "JOIN venues v ON v.id = pa.venue_id "
            "WHERE v.city = 'Birmingham' "
            "GROUP BY v.id, v.name"
        ),
        "key_columns": ("venue", "batting_innings"),
        "ground_truth_note": "Counts batting player-match pairs at Birmingham venues.",
    },

    # ── D: Multi-pattern conjunction ─────────────────────────────────────────

    {
        "name": "SQ_D01_allrounders",
        "question": "Which players both batted and bowled in the same match and how many such matches did each have? Order by match count descending.",
        "query_class": "multi_pattern",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS allrounder_matches "
            "FROM batted_in bi "
            "JOIN bowled_in bw ON bi.player_id = bw.player_id AND bi.match_id = bw.match_id "
            "JOIN players p ON p.id = bi.player_id "
            "GROUP BY p.id, p.name ORDER BY allrounder_matches DESC"
        ),
        "key_columns": ("name", "allrounder_matches"),
        "ground_truth_note": "Inner join on (player, match) across BATTED_IN and BOWLED_IN.",
    },
    {
        "name": "SQ_D02_pak_test_allrounders",
        "question": "Which Pakistani players both batted and bowled in the same Test match and how many times?",
        "query_class": "multi_pattern",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS test_allrounder_matches "
            "FROM batted_in bi "
            "JOIN bowled_in bw ON bi.player_id = bw.player_id AND bi.match_id = bw.match_id "
            "JOIN players p ON p.id = bi.player_id "
            "JOIN matches m ON m.id = bi.match_id "
            "WHERE p.country = 'PAK' AND m.format = 'Test' "
            "GROUP BY p.id, p.name ORDER BY test_allrounder_matches DESC"
        ),
        "key_columns": ("name", "test_allrounder_matches"),
        "ground_truth_note": "PAK all-rounders in Test format. Fixture: Mitchell Starc (1 match).",
    },
    {
        "name": "SQ_D03_captain_batting_runs",
        "question": "How many runs did each player score in matches they captained? Order by runs descending.",
        "query_class": "multi_pattern",
        "sql": (
            "SELECT p.name AS name, SUM(bi.runs) AS captain_batting_runs "
            "FROM captained ca "
            "JOIN batted_in bi ON ca.player_id = bi.player_id AND ca.match_id = bi.match_id "
            "JOIN players p ON p.id = ca.player_id "
            "GROUP BY p.id, p.name ORDER BY captain_batting_runs DESC"
        ),
        "key_columns": ("name", "captain_batting_runs"),
        "ground_truth_note": "Runs scored in matches where the player was also captain.",
    },
    {
        "name": "SQ_D04_captain_bowling_wickets",
        "question": "How many wickets did each player take in matches they captained? Order by wickets descending.",
        "query_class": "multi_pattern",
        "sql": (
            "SELECT p.name AS name, SUM(bw.wickets) AS captain_wickets "
            "FROM captained ca "
            "JOIN bowled_in bw ON ca.player_id = bw.player_id AND ca.match_id = bw.match_id "
            "JOIN players p ON p.id = ca.player_id "
            "GROUP BY p.id, p.name ORDER BY captain_wickets DESC"
        ),
        "key_columns": ("name", "captain_wickets"),
        "ground_truth_note": "Wickets taken in matches where the player was also captain.",
    },
    {
        "name": "SQ_D05_t20_allrounders",
        "question": "Which players both batted and bowled in the same T20 match and how many such T20 matches did each have?",
        "query_class": "multi_pattern",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS t20_allrounder_matches "
            "FROM batted_in bi "
            "JOIN bowled_in bw ON bi.player_id = bw.player_id AND bi.match_id = bw.match_id "
            "JOIN players p ON p.id = bi.player_id "
            "JOIN matches m ON m.id = bi.match_id "
            "WHERE m.format = 'T20' "
            "GROUP BY p.id, p.name ORDER BY t20_allrounder_matches DESC"
        ),
        "key_columns": ("name", "t20_allrounder_matches"),
        "ground_truth_note": "T20 all-rounder matches per player.",
    },
    {
        "name": "SQ_D06_allrounder_bat_bowl_stats",
        "question": "For players who both batted and bowled in the same match, what are their total runs and wickets in those matches? Show top 10 by runs.",
        "query_class": "multi_pattern",
        "sql": (
            "SELECT p.name AS name, SUM(bi.runs) AS bat_runs, SUM(bw.wickets) AS bowl_wickets "
            "FROM batted_in bi "
            "JOIN bowled_in bw ON bi.player_id = bw.player_id AND bi.match_id = bw.match_id "
            "JOIN players p ON p.id = bi.player_id "
            "GROUP BY p.id, p.name ORDER BY bat_runs DESC LIMIT 10"
        ),
        "key_columns": ("name", "bat_runs", "bowl_wickets"),
        "ground_truth_note": "Combined batting+bowling stats in same-match all-round performances.",
    },
    {
        "name": "SQ_D07_aus_allrounders",
        "question": "Which Australian players both batted and bowled in the same match and how many times?",
        "query_class": "multi_pattern",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS matches "
            "FROM batted_in bi "
            "JOIN bowled_in bw ON bi.player_id = bw.player_id AND bi.match_id = bw.match_id "
            "JOIN players p ON p.id = bi.player_id "
            "WHERE p.country = 'AUS' "
            "GROUP BY p.id, p.name ORDER BY matches DESC"
        ),
        "key_columns": ("name", "matches"),
        "ground_truth_note": "Australian all-rounders.",
    },
    {
        "name": "SQ_D08_captain_runs_by_format",
        "question": "How many runs did captains score in their captained matches, grouped by format? Order by runs descending.",
        "query_class": "multi_pattern",
        "sql": (
            "SELECT m.format AS format, SUM(bi.runs) AS captain_runs "
            "FROM captained ca "
            "JOIN batted_in bi ON ca.player_id = bi.player_id AND ca.match_id = bi.match_id "
            "JOIN matches m ON m.id = ca.match_id "
            "GROUP BY m.format ORDER BY captain_runs DESC"
        ),
        "key_columns": ("format", "captain_runs"),
        "ground_truth_note": "Captain batting runs grouped by match format.",
    },
    {
        "name": "SQ_D09_test_allrounders_with_wicket",
        "question": "Which players took at least 1 wicket in a Test match where they also batted? Show their runs and wickets, top 10 by wickets descending.",
        "query_class": "multi_pattern",
        "sql": (
            "SELECT p.name AS name, SUM(bi.runs) AS runs, SUM(bw.wickets) AS wickets "
            "FROM batted_in bi "
            "JOIN bowled_in bw ON bi.player_id = bw.player_id AND bi.match_id = bw.match_id "
            "JOIN players p ON p.id = bi.player_id "
            "JOIN matches m ON m.id = bi.match_id "
            "WHERE m.format = 'Test' AND bw.wickets >= 1 "
            "GROUP BY p.id, p.name ORDER BY wickets DESC LIMIT 10"
        ),
        "key_columns": ("name", "runs", "wickets"),
        "ground_truth_note": "Test all-round with at least 1 wicket.",
    },
    {
        "name": "SQ_D10_sri_allrounders",
        "question": "Which Sri Lankan players both batted and bowled in the same match? Show their match count and total runs.",
        "query_class": "multi_pattern",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS matches, SUM(bi.runs) AS runs "
            "FROM batted_in bi "
            "JOIN bowled_in bw ON bi.player_id = bw.player_id AND bi.match_id = bw.match_id "
            "JOIN players p ON p.id = bi.player_id "
            "WHERE p.country = 'SRI' "
            "GROUP BY p.id, p.name ORDER BY runs DESC"
        ),
        "key_columns": ("name", "matches", "runs"),
        "ground_truth_note": "Sri Lankan all-rounders.",
    },
    {
        "name": "SQ_D11_pak_captain_t20_runs",
        "question": "How many runs did players score in T20 matches they captained? Order by runs descending.",
        "query_class": "multi_pattern",
        "sql": (
            "SELECT p.name AS name, SUM(bi.runs) AS t20_captain_runs "
            "FROM captained ca "
            "JOIN batted_in bi ON ca.player_id = bi.player_id AND ca.match_id = bi.match_id "
            "JOIN players p ON p.id = ca.player_id "
            "JOIN matches m ON m.id = ca.match_id "
            "WHERE m.format = 'T20' "
            "GROUP BY p.id, p.name ORDER BY t20_captain_runs DESC"
        ),
        "key_columns": ("name", "t20_captain_runs"),
        "ground_truth_note": "T20 captain batting runs.",
    },
    {
        "name": "SQ_D12_ind_allrounders",
        "question": "Which Indian players both batted and bowled in the same match? Show their total runs and wickets.",
        "query_class": "multi_pattern",
        "sql": (
            "SELECT p.name AS name, SUM(bi.runs) AS runs, SUM(bw.wickets) AS wickets "
            "FROM batted_in bi "
            "JOIN bowled_in bw ON bi.player_id = bw.player_id AND bi.match_id = bw.match_id "
            "JOIN players p ON p.id = bi.player_id "
            "WHERE p.country = 'IND' "
            "GROUP BY p.id, p.name ORDER BY runs DESC"
        ),
        "key_columns": ("name", "runs", "wickets"),
        "ground_truth_note": "Indian all-rounders.",
    },

    # ── E: Undirected edge queries ───────────────────────────────────────────

    {
        "name": "SQ_E01_babar_teammates",
        "question": "Who are Babar Azam's teammates and how many matches did they play together? Order by shared matches descending.",
        "query_class": "undirected",
        "sql": (
            "SELECT p2.name AS teammate, tw.match_count AS shared_matches "
            "FROM players p1 "
            "JOIN teammates_with tw ON (tw.player_a_id = p1.id OR tw.player_b_id = p1.id) "
            "JOIN players p2 ON p2.id = CASE WHEN tw.player_a_id = p1.id "
            "    THEN tw.player_b_id ELSE tw.player_a_id END "
            "WHERE p1.name = 'Babar Azam' "
            "ORDER BY shared_matches DESC"
        ),
        "key_columns": ("teammate", "shared_matches"),
        "ground_truth_note": "Fixture: 4 teammates (Rizwan×4, Shaheen×3, Naseem×1, Shan×1).",
    },
    {
        "name": "SQ_E02_rizwan_teammates",
        "question": "Who are Mohammad Rizwan's teammates and how many matches did they share? Order by shared matches descending.",
        "query_class": "undirected",
        "sql": (
            "SELECT p2.name AS teammate, tw.match_count AS shared_matches "
            "FROM players p1 "
            "JOIN teammates_with tw ON (tw.player_a_id = p1.id OR tw.player_b_id = p1.id) "
            "JOIN players p2 ON p2.id = CASE WHEN tw.player_a_id = p1.id "
            "    THEN tw.player_b_id ELSE tw.player_a_id END "
            "WHERE p1.name = 'Mohammad Rizwan' "
            "ORDER BY shared_matches DESC"
        ),
        "key_columns": ("teammate", "shared_matches"),
        "ground_truth_note": "Undirected TEAMMATES_WITH traversal from Rizwan.",
    },
    {
        "name": "SQ_E03_most_connected_players",
        "question": "Which players have the most teammates? Show the top 10 ordered by teammate count descending.",
        "query_class": "undirected",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS teammate_count "
            "FROM players p "
            "JOIN teammates_with tw ON (tw.player_a_id = p.id OR tw.player_b_id = p.id) "
            "GROUP BY p.id, p.name ORDER BY teammate_count DESC LIMIT 10"
        ),
        "key_columns": ("name", "teammate_count"),
        "ground_truth_note": "Degree centrality via undirected TEAMMATES_WITH.",
    },
    {
        "name": "SQ_E04_babar_top_teammates",
        "question": "Who are Babar Azam's 5 most frequent teammates by number of shared matches?",
        "query_class": "undirected",
        "sql": (
            "SELECT p2.name AS teammate, tw.match_count AS shared_matches "
            "FROM players p1 "
            "JOIN teammates_with tw ON (tw.player_a_id = p1.id OR tw.player_b_id = p1.id) "
            "JOIN players p2 ON p2.id = CASE WHEN tw.player_a_id = p1.id "
            "    THEN tw.player_b_id ELSE tw.player_a_id END "
            "WHERE p1.name = 'Babar Azam' "
            "ORDER BY shared_matches DESC LIMIT 5"
        ),
        "key_columns": ("teammate", "shared_matches"),
        "ground_truth_note": "Top 5 teammates by shared match count.",
    },
    {
        "name": "SQ_E05_pak_player_teammate_counts",
        "question": "How many teammates does each Pakistani player have? Show the top 10 ordered by teammate count descending.",
        "query_class": "undirected",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS teammate_count "
            "FROM players p "
            "JOIN teammates_with tw ON (tw.player_a_id = p.id OR tw.player_b_id = p.id) "
            "WHERE p.country = 'PAK' "
            "GROUP BY p.id, p.name ORDER BY teammate_count DESC LIMIT 10"
        ),
        "key_columns": ("name", "teammate_count"),
        "ground_truth_note": "PAK-only teammate degree.",
    },
    {
        "name": "SQ_E06_shaheen_teammates",
        "question": "Who are Shaheen Afridi's teammates and how many matches did they share?",
        "query_class": "undirected",
        "sql": (
            "SELECT p2.name AS teammate, tw.match_count AS shared_matches "
            "FROM players p1 "
            "JOIN teammates_with tw ON (tw.player_a_id = p1.id OR tw.player_b_id = p1.id) "
            "JOIN players p2 ON p2.id = CASE WHEN tw.player_a_id = p1.id "
            "    THEN tw.player_b_id ELSE tw.player_a_id END "
            "WHERE p1.name = 'Shaheen Afridi' "
            "ORDER BY shared_matches DESC"
        ),
        "key_columns": ("teammate", "shared_matches"),
        "ground_truth_note": "Shaheen Afridi teammate connections.",
    },
    {
        "name": "SQ_E07_highest_match_count_pairs",
        "question": "Which player pairs played together in the most matches? Show the top 10 ordered by shared match count descending.",
        "query_class": "undirected",
        "sql": (
            "SELECT p.name AS player_a, t.name AS player_b, tw.match_count AS shared_matches "
            "FROM teammates_with tw "
            "JOIN players p ON p.id = tw.player_a_id "
            "JOIN players t ON t.id = tw.player_b_id "
            "ORDER BY shared_matches DESC LIMIT 10"
        ),
        "key_columns": ("player_a", "player_b", "shared_matches"),
        "ground_truth_note": (
            "Uses directed edge (canonical src=min(id)) to avoid duplicate pairs."
        ),
    },
    {
        "name": "SQ_E08_naseem_teammates",
        "question": "Who are Naseem Shah's teammates and how many matches did they share?",
        "query_class": "undirected",
        "sql": (
            "SELECT p2.name AS teammate, tw.match_count AS shared_matches "
            "FROM players p1 "
            "JOIN teammates_with tw ON (tw.player_a_id = p1.id OR tw.player_b_id = p1.id) "
            "JOIN players p2 ON p2.id = CASE WHEN tw.player_a_id = p1.id "
            "    THEN tw.player_b_id ELSE tw.player_a_id END "
            "WHERE p1.name = 'Naseem Shah' "
            "ORDER BY shared_matches DESC"
        ),
        "key_columns": ("teammate", "shared_matches"),
        "ground_truth_note": "Naseem Shah teammate connections.",
    },
    {
        "name": "SQ_E09_ind_pak_teammate_pairs",
        "question": "Which Indian players were teammates of Pakistani players, and for how many matches? Show top 10.",
        "query_class": "undirected",
        "sql": (
            "SELECT p.name AS ind_player, t.name AS pak_player, tw.match_count AS shared_matches "
            "FROM players p "
            "JOIN teammates_with tw ON (tw.player_a_id = p.id OR tw.player_b_id = p.id) "
            "JOIN players t ON t.id = CASE WHEN tw.player_a_id = p.id "
            "    THEN tw.player_b_id ELSE tw.player_a_id END "
            "WHERE p.country = 'IND' AND t.country = 'PAK' "
            "ORDER BY shared_matches DESC LIMIT 10"
        ),
        "key_columns": ("ind_player", "pak_player", "shared_matches"),
        "ground_truth_note": "Cross-country teammate pairs (IND–PAK).",
    },
    {
        "name": "SQ_E10_high_match_count_pairs",
        "question": "Which player pairs played together in 2 or more matches? Order by shared match count descending.",
        "query_class": "undirected",
        "sql": (
            "SELECT p.name AS player_a, t.name AS player_b, tw.match_count AS shared_matches "
            "FROM teammates_with tw "
            "JOIN players p ON p.id = tw.player_a_id "
            "JOIN players t ON t.id = tw.player_b_id "
            "WHERE tw.match_count >= 2 "
            "ORDER BY shared_matches DESC"
        ),
        "key_columns": ("player_a", "player_b", "shared_matches"),
        "ground_truth_note": "Pairs who played 2+ matches together.",
    },

    # ── F: RPQ / bounded Kleene-star ─────────────────────────────────────────

    {
        "name": "SQ_F01_next_delivery_1_hop",
        "question": "What is the id of the delivery immediately after delivery {start_id}?",
        "query_class": "rpq",
        "needs_start_id": True,
        "sql": (
            "SELECT e.id AS delivery_id "
            "FROM next_delivery nd "
            "JOIN deliveries e ON e.id = nd.next_id "
            "WHERE nd.prev_id = '{start_id}'"
        ),
        "key_columns": ("delivery_id",),
        "ground_truth_note": "Exactly 1 hop via NEXT_DELIVERY. Returns 0 rows if start is chain end.",
    },
    {
        "name": "SQ_F02_next_delivery_1_to_3",
        "question": "Which delivery ids are reachable in 1 to 3 hops from delivery {start_id} via the next-delivery chain?",
        "query_class": "rpq",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ("
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT nd.next_id, chain.depth + 1 FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id WHERE chain.depth < 3"
            ") "
            "SELECT DISTINCT end_id AS delivery_id FROM chain ORDER BY delivery_id"
        ),
        "key_columns": ("delivery_id",),
        "ground_truth_note": "RPQ *1..3 from start. BFS deduplicates on node id.",
    },
    {
        "name": "SQ_F03_next_delivery_star_count",
        "question": "How many deliveries are reachable from delivery {start_id} following the next-delivery chain without any hop limit?",
        "query_class": "rpq",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id) AS ("
            "  SELECT next_id FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION "
            "  SELECT nd.next_id FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id"
            ") "
            "SELECT COUNT(*) AS reachable_count FROM chain"
        ),
        "key_columns": ("reachable_count",),
        "ground_truth_note": "Unbounded traversal. UNION (not UNION ALL) for deduplication.",
    },
    {
        "name": "SQ_F04_next_delivery_exact_2",
        "question": "What is the id of the delivery exactly 2 hops away from delivery {start_id}?",
        "query_class": "rpq",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ("
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT nd.next_id, chain.depth + 1 FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id WHERE chain.depth < 2"
            ") "
            "SELECT end_id AS delivery_id FROM chain WHERE depth = 2"
        ),
        "key_columns": ("delivery_id",),
        "ground_truth_note": "Exactly 2 hops.",
    },
    {
        "name": "SQ_F05_next_delivery_0_to_3_count",
        "question": "How many deliveries are reachable in 0 to 3 hops from delivery {start_id}, including the start delivery itself?",
        "query_class": "rpq",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ("
            "  SELECT '{start_id}' AS end_id, 0 AS depth "
            "  UNION ALL "
            "  SELECT nd.next_id, chain.depth + 1 FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id WHERE chain.depth < 3"
            ") "
            "SELECT COUNT(DISTINCT end_id) AS reachable_count FROM chain"
        ),
        "key_columns": ("reachable_count",),
        "ground_truth_note": "Includes start node (depth 0). Fixture start of 7-chain: 4.",
    },
    {
        "name": "SQ_F06_next_delivery_plus_count",
        "question": "How many deliveries are reachable via one or more hops from delivery {start_id}?",
        "query_class": "rpq",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id) AS ("
            "  SELECT next_id FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION "
            "  SELECT nd.next_id FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id"
            ") "
            "SELECT COUNT(*) AS reachable_count FROM chain"
        ),
        "key_columns": ("reachable_count",),
        "ground_truth_note": "One-or-more hops.",
    },
    {
        "name": "SQ_F07_next_delivery_1_to_5_count",
        "question": "How many deliveries are reachable in 1 to 5 hops from delivery {start_id}?",
        "query_class": "rpq",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ("
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT nd.next_id, chain.depth + 1 FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id WHERE chain.depth < 5"
            ") "
            "SELECT COUNT(DISTINCT end_id) AS reachable_count FROM chain"
        ),
        "key_columns": ("reachable_count",),
        "ground_truth_note": "Bounded range *1..5.",
    },
    {
        "name": "SQ_F08_next_delivery_2_to_4_count",
        "question": "How many deliveries are at a shortest-path distance of 2 to 4 hops from delivery {start_id}?",
        "query_class": "rpq",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ("
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT nd.next_id, chain.depth + 1 FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id WHERE chain.depth < 4"
            ") "
            "SELECT COUNT(DISTINCT end_id) AS reachable_count FROM chain WHERE depth >= 2"
        ),
        "key_columns": ("reachable_count",),
        "ground_truth_note": "Nodes at shortest depth 2–4.",
    },
    {
        "name": "SQ_F09_next_delivery_exact_3",
        "question": "What is the id of the delivery exactly 3 hops away from delivery {start_id}?",
        "query_class": "rpq",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ("
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT nd.next_id, chain.depth + 1 FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id WHERE chain.depth < 3"
            ") "
            "SELECT end_id AS delivery_id FROM chain WHERE depth = 3"
        ),
        "key_columns": ("delivery_id",),
        "ground_truth_note": "Exactly 3 hops. Returns 0 rows if chain is shorter.",
    },
    {
        "name": "SQ_F10_next_delivery_star_ids",
        "question": "List all delivery ids reachable from delivery {start_id} via the next-delivery chain, ordered by id.",
        "query_class": "rpq",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id) AS ("
            "  SELECT next_id FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION "
            "  SELECT nd.next_id FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id"
            ") "
            "SELECT end_id AS delivery_id FROM chain ORDER BY delivery_id"
        ),
        "key_columns": ("delivery_id",),
        "ground_truth_note": "Full reachable set via unbounded traversal.",
    },

    # ── G: RPQ + target-side property filter ─────────────────────────────────

    {
        "name": "SQ_G01_scoring_within_5",
        "question": "How many scoring deliveries (where runs_total is greater than 0) are reachable within 5 hops from delivery {start_id}?",
        "query_class": "rpq_filter",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ("
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT nd.next_id, chain.depth + 1 FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id WHERE chain.depth < 5"
            ") "
            "SELECT COUNT(DISTINCT e.id) AS scoring_deliveries "
            "FROM chain JOIN deliveries e ON e.id = chain.end_id "
            "WHERE e.runs_total > 0"
        ),
        "key_columns": ("scoring_deliveries",),
        "ground_truth_note": "RPQ *1..5 with target filter runs_total > 0.",
    },
    {
        "name": "SQ_G02_sixes_within_10",
        "question": "How many six-run deliveries (where runs_batter equals 6) are reachable within 10 hops from delivery {start_id}?",
        "query_class": "rpq_filter",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ("
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT nd.next_id, chain.depth + 1 FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id WHERE chain.depth < 10"
            ") "
            "SELECT COUNT(DISTINCT e.id) AS sixes_in_range "
            "FROM chain JOIN deliveries e ON e.id = chain.end_id "
            "WHERE e.runs_batter = 6"
        ),
        "key_columns": ("sixes_in_range",),
        "ground_truth_note": "RPQ *1..10 filtered to batter sixes.",
    },
    {
        "name": "SQ_G03_boundaries_within_6",
        "question": "How many boundary deliveries (where runs_total is 4 or more) are reachable within 6 hops from delivery {start_id}?",
        "query_class": "rpq_filter",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ("
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT nd.next_id, chain.depth + 1 FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id WHERE chain.depth < 6"
            ") "
            "SELECT COUNT(DISTINCT e.id) AS boundaries_in_range "
            "FROM chain JOIN deliveries e ON e.id = chain.end_id "
            "WHERE e.runs_total >= 4"
        ),
        "key_columns": ("boundaries_in_range",),
        "ground_truth_note": "RPQ *1..6 filtered to total runs >= 4.",
    },
    {
        "name": "SQ_G04_dot_balls_within_4",
        "question": "How many dot-ball deliveries (where runs_total equals 0) are reachable within 4 hops from delivery {start_id}?",
        "query_class": "rpq_filter",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ("
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT nd.next_id, chain.depth + 1 FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id WHERE chain.depth < 4"
            ") "
            "SELECT COUNT(DISTINCT e.id) AS dot_balls_in_range "
            "FROM chain JOIN deliveries e ON e.id = chain.end_id "
            "WHERE e.runs_total = 0"
        ),
        "key_columns": ("dot_balls_in_range",),
        "ground_truth_note": "RPQ *1..4 filtered to zero-run deliveries.",
    },
    {
        "name": "SQ_G05_multi_run_within_8",
        "question": "How many deliveries with more than 1 batter run are reachable within 8 hops from delivery {start_id}?",
        "query_class": "rpq_filter",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ("
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT nd.next_id, chain.depth + 1 FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id WHERE chain.depth < 8"
            ") "
            "SELECT COUNT(DISTINCT e.id) AS multi_run_deliveries "
            "FROM chain JOIN deliveries e ON e.id = chain.end_id "
            "WHERE e.runs_batter > 1"
        ),
        "key_columns": ("multi_run_deliveries",),
        "ground_truth_note": "RPQ *1..8 filtered to runs_batter > 1.",
    },
    {
        "name": "SQ_G06_extras_within_10",
        "question": "How many deliveries with extras (runs_extras greater than 0) are reachable within 10 hops from delivery {start_id}?",
        "query_class": "rpq_filter",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ("
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT nd.next_id, chain.depth + 1 FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id WHERE chain.depth < 10"
            ") "
            "SELECT COUNT(DISTINCT e.id) AS extras_deliveries "
            "FROM chain JOIN deliveries e ON e.id = chain.end_id "
            "WHERE e.runs_extras > 0"
        ),
        "key_columns": ("extras_deliveries",),
        "ground_truth_note": "RPQ *1..10 filtered to deliveries with any extras.",
    },
    {
        "name": "SQ_G07_nonzero_within_7",
        "question": "How many deliveries where runs_total is not zero are reachable within 7 hops from delivery {start_id}?",
        "query_class": "rpq_filter",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ("
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT nd.next_id, chain.depth + 1 FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id WHERE chain.depth < 7"
            ") "
            "SELECT COUNT(DISTINCT e.id) AS non_dot_deliveries "
            "FROM chain JOIN deliveries e ON e.id = chain.end_id "
            "WHERE e.runs_total != 0"
        ),
        "key_columns": ("non_dot_deliveries",),
        "ground_truth_note": "RPQ *1..7 filtered to runs_total != 0.",
    },
    {
        "name": "SQ_G08_batter_2plus_within_5",
        "question": "Which delivery ids within 5 hops of delivery {start_id} have 2 or more batter runs? Order by id.",
        "query_class": "rpq_filter",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ("
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT nd.next_id, chain.depth + 1 FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id WHERE chain.depth < 5"
            ") "
            "SELECT DISTINCT e.id AS delivery_id "
            "FROM chain JOIN deliveries e ON e.id = chain.end_id "
            "WHERE e.runs_batter >= 2 ORDER BY delivery_id"
        ),
        "key_columns": ("delivery_id",),
        "ground_truth_note": "IDs of deliveries with runs_batter >= 2 within 5 hops.",
    },
    {
        "name": "SQ_G09_low_scoring_within_6",
        "question": "How many low-scoring deliveries (runs_total 1 or less) are reachable within 6 hops from delivery {start_id}?",
        "query_class": "rpq_filter",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ("
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT nd.next_id, chain.depth + 1 FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id WHERE chain.depth < 6"
            ") "
            "SELECT COUNT(DISTINCT e.id) AS low_scoring "
            "FROM chain JOIN deliveries e ON e.id = chain.end_id "
            "WHERE e.runs_total <= 1"
        ),
        "key_columns": ("low_scoring",),
        "ground_truth_note": "RPQ *1..6 filtered to runs_total <= 1.",
    },
    {
        "name": "SQ_G10_no_extras_within_3",
        "question": "How many deliveries with no extras (runs_extras equals 0) are reachable within 3 hops from delivery {start_id}?",
        "query_class": "rpq_filter",
        "needs_start_id": True,
        "sql": (
            "WITH RECURSIVE chain(end_id, depth) AS ("
            "  SELECT next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' "
            "  UNION ALL "
            "  SELECT nd.next_id, chain.depth + 1 FROM chain "
            "  JOIN next_delivery nd ON nd.prev_id = chain.end_id WHERE chain.depth < 3"
            ") "
            "SELECT COUNT(DISTINCT e.id) AS clean_deliveries "
            "FROM chain JOIN deliveries e ON e.id = chain.end_id "
            "WHERE e.runs_extras = 0"
        ),
        "key_columns": ("clean_deliveries",),
        "ground_truth_note": "RPQ *1..3 filtered to deliveries without extras.",
    },

    # ── H: Negation & boolean composition ────────────────────────────────────

    {
        "name": "SQ_H01_non_pak_players",
        "question": "Which players are not from Pakistan? List their names and countries ordered by country then name.",
        "query_class": "negation",
        "sql": (
            "SELECT name, country FROM players "
            "WHERE country != 'PAK' ORDER BY country, name"
        ),
        "key_columns": ("name", "country"),
        "ground_truth_note": "Fixture: 11 non-PAK players.",
    },
    {
        "name": "SQ_H02_non_test_match_count",
        "question": "How many matches in the dataset are not Test matches?",
        "query_class": "negation",
        "sql": "SELECT COUNT(*) AS non_test_matches FROM matches WHERE format != 'Test'",
        "key_columns": ("non_test_matches",),
        "ground_truth_note": "Fixture: 4 (all T20). Full corpus: ~675.",
    },
    {
        "name": "SQ_H03_zero_run_innings",
        "question": "Which players have the most batting innings where they scored 0 runs? Show the top 10.",
        "query_class": "negation",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS zero_run_innings "
            "FROM players p JOIN batted_in bi ON bi.player_id = p.id "
            "WHERE bi.runs = 0 "
            "GROUP BY p.id, p.name ORDER BY zero_run_innings DESC LIMIT 10"
        ),
        "key_columns": ("name", "zero_run_innings"),
        "ground_truth_note": "Innings where batter scored exactly 0.",
    },
    {
        "name": "SQ_H04_wicketless_bowling_innings",
        "question": "Which bowlers have the most bowling innings without taking a wicket? Show the top 10.",
        "query_class": "negation",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS wicketless_innings "
            "FROM players p JOIN bowled_in bw ON bw.player_id = p.id "
            "WHERE bw.wickets = 0 "
            "GROUP BY p.id, p.name ORDER BY wicketless_innings DESC LIMIT 10"
        ),
        "key_columns": ("name", "wicketless_innings"),
        "ground_truth_note": "Bowling innings with 0 wickets taken.",
    },
    {
        "name": "SQ_H05_boundaryless_innings",
        "question": "Which players have the most batting innings with no boundaries at all (zero fours and zero sixes)? Show the top 10.",
        "query_class": "negation",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS boundaryless_innings "
            "FROM players p JOIN batted_in bi ON bi.player_id = p.id "
            "WHERE bi.fours = 0 AND bi.sixes = 0 "
            "GROUP BY p.id, p.name ORDER BY boundaryless_innings DESC LIMIT 10"
        ),
        "key_columns": ("name", "boundaryless_innings"),
        "ground_truth_note": "Fixture: 9 boundaryless batting innings.",
    },
    {
        "name": "SQ_H06_no_six_t20_innings",
        "question": "Which players have the most T20 batting innings without hitting a six? Show the top 10.",
        "query_class": "negation",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS no_six_t20_innings "
            "FROM players p "
            "JOIN batted_in bi ON bi.player_id = p.id "
            "JOIN matches m ON m.id = bi.match_id "
            "WHERE bi.sixes = 0 AND m.format = 'T20' "
            "GROUP BY p.id, p.name ORDER BY no_six_t20_innings DESC LIMIT 10"
        ),
        "key_columns": ("name", "no_six_t20_innings"),
        "ground_truth_note": "T20 innings where sixes=0.",
    },
    {
        "name": "SQ_H07_matches_not_won_by_pak",
        "question": "How many matches did Pakistan not win, among matches with a recorded winner?",
        "query_class": "negation",
        "sql": (
            "SELECT COUNT(*) AS matches_not_won_by_pak "
            "FROM matches WHERE outcome_winner != 'Pakistan'"
        ),
        "key_columns": ("matches_not_won_by_pak",),
        "ground_truth_note": "Excludes matches with no recorded winner (NULL outcome_winner).",
    },
    {
        "name": "SQ_H08_non_t20_non_test_matches",
        "question": "How many matches are neither T20 nor Test format?",
        "query_class": "negation",
        "sql": (
            "SELECT COUNT(*) AS other_format_matches "
            "FROM matches WHERE format != 'T20' AND format != 'Test'"
        ),
        "key_columns": ("other_format_matches",),
        "ground_truth_note": "Fixture: 0. Full corpus: ODI + IT20 + others.",
    },
    {
        "name": "SQ_H09_bowling_with_wickets",
        "question": "Which bowlers have taken at least 1 wicket? Show their total wickets, top 10 ordered by wickets descending.",
        "query_class": "negation",
        "sql": (
            "SELECT p.name AS name, SUM(bw.wickets) AS wickets "
            "FROM players p JOIN bowled_in bw ON bw.player_id = p.id "
            "WHERE bw.wickets != 0 "
            "GROUP BY p.id, p.name ORDER BY wickets DESC LIMIT 10"
        ),
        "key_columns": ("name", "wickets"),
        "ground_truth_note": "Bowling innings with wickets != 0.",
    },
    {
        "name": "SQ_H10_non_pak_test_batters",
        "question": "Which non-Pakistani players scored the most runs in Test matches? Show the top 10.",
        "query_class": "negation",
        "sql": (
            "SELECT p.name AS name, SUM(bi.runs) AS test_runs "
            "FROM players p "
            "JOIN batted_in bi ON bi.player_id = p.id "
            "JOIN matches m ON m.id = bi.match_id "
            "WHERE p.country != 'PAK' AND m.format = 'Test' "
            "GROUP BY p.id, p.name ORDER BY test_runs DESC LIMIT 10"
        ),
        "key_columns": ("name", "test_runs"),
        "ground_truth_note": "Non-PAK Test batters.",
    },
    {
        "name": "SQ_H11_runs_no_sixes",
        "question": "Which players have the most batting innings where they scored runs but hit no sixes? Show the top 10.",
        "query_class": "negation",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS no_six_innings "
            "FROM players p JOIN batted_in bi ON bi.player_id = p.id "
            "WHERE bi.runs > 0 AND bi.sixes = 0 "
            "GROUP BY p.id, p.name ORDER BY no_six_innings DESC LIMIT 10"
        ),
        "key_columns": ("name", "no_six_innings"),
        "ground_truth_note": "Innings with runs scored but no sixes.",
    },
    {
        "name": "SQ_H12_pak_or_test_innings",
        "question": "Which players scored the most runs in innings that were either by a Pakistani player or in a Test match? Show the top 10.",
        "query_class": "negation",
        "sql": (
            "SELECT p.name AS name, SUM(bi.runs) AS runs "
            "FROM players p "
            "JOIN batted_in bi ON bi.player_id = p.id "
            "JOIN matches m ON m.id = bi.match_id "
            "WHERE p.country = 'PAK' OR m.format = 'Test' "
            "GROUP BY p.id, p.name ORDER BY runs DESC LIMIT 10"
        ),
        "key_columns": ("name", "runs"),
        "ground_truth_note": "OR composition: PAK players union Test-match batters.",
    },

    # ── I: Hard / compound multi-constraint ──────────────────────────────────

    {
        "name": "SQ_I01_runs_by_format_per_player",
        "question": "How many total runs did each player score in each format? Order by format then runs descending.",
        "query_class": "hard",
        "sql": (
            "SELECT m.format AS format, p.name AS name, SUM(bi.runs) AS total_runs "
            "FROM players p "
            "JOIN batted_in bi ON bi.player_id = p.id "
            "JOIN matches m ON m.id = bi.match_id "
            "GROUP BY m.format, p.id, p.name ORDER BY format, total_runs DESC"
        ),
        "key_columns": ("format", "name", "total_runs"),
        "ground_truth_note": "Two-level GROUP BY: format × player.",
    },
    {
        "name": "SQ_I02_heroic_allround_matches",
        "question": "Which players scored at least 20 runs and took at least 2 wickets in the same match and how many such matches did each have?",
        "query_class": "hard",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS heroic_matches "
            "FROM batted_in bi "
            "JOIN bowled_in bw ON bi.player_id = bw.player_id AND bi.match_id = bw.match_id "
            "JOIN players p ON p.id = bi.player_id "
            "WHERE bi.runs >= 20 AND bw.wickets >= 2 "
            "GROUP BY p.id, p.name ORDER BY heroic_matches DESC"
        ),
        "key_columns": ("name", "heroic_matches"),
        "ground_truth_note": "Multi-pattern + dual inequality filter.",
    },
    {
        "name": "SQ_I03_wickets_per_venue_top5",
        "question": "Which 5 venues saw the most wickets taken in total?",
        "query_class": "hard",
        "sql": (
            "SELECT v.name AS venue, SUM(bw.wickets) AS total_wickets "
            "FROM bowled_in bw "
            "JOIN matches m ON m.id = bw.match_id "
            "JOIN played_at pa ON pa.match_id = m.id "
            "JOIN venues v ON v.id = pa.venue_id "
            "GROUP BY v.id, v.name ORDER BY total_wickets DESC LIMIT 5"
        ),
        "key_columns": ("venue", "total_wickets"),
        "ground_truth_note": "Multi-hop (2 edges) + aggregation, top 5.",
    },
    {
        "name": "SQ_I04_pak_test_captain_batting",
        "question": "How many runs did each Pakistani player score in Test matches they captained? Show innings count and total runs, ordered by runs descending.",
        "query_class": "hard",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS test_captain_innings, SUM(bi.runs) AS total_runs "
            "FROM captained ca "
            "JOIN batted_in bi ON ca.player_id = bi.player_id AND ca.match_id = bi.match_id "
            "JOIN players p ON p.id = ca.player_id "
            "JOIN matches m ON m.id = ca.match_id "
            "WHERE p.country = 'PAK' AND m.format = 'Test' "
            "GROUP BY p.id, p.name ORDER BY total_runs DESC"
        ),
        "key_columns": ("name", "test_captain_innings", "total_runs"),
        "ground_truth_note": "Multi-pattern + format filter + country filter.",
    },
    {
        "name": "SQ_I05_pak_boundaries_by_season",
        "question": "How many fours and sixes did Pakistani players hit per season? Show the top 10 seasons ordered by fours descending.",
        "query_class": "hard",
        "sql": (
            "SELECT m.season AS season, SUM(bi.fours) AS total_fours, SUM(bi.sixes) AS total_sixes "
            "FROM players p "
            "JOIN batted_in bi ON bi.player_id = p.id "
            "JOIN matches m ON m.id = bi.match_id "
            "WHERE p.country = 'PAK' "
            "GROUP BY m.season ORDER BY total_fours DESC LIMIT 10"
        ),
        "key_columns": ("season", "total_fours", "total_sixes"),
        "ground_truth_note": "PAK boundary stats grouped by season.",
    },
    {
        "name": "SQ_I06_test_expensive_wicket_takers",
        "question": "Which bowlers conceded at least 30 runs and took at least 1 wicket in the same Test match innings? Show the top 10 by such match count.",
        "query_class": "hard",
        "sql": (
            "SELECT p.name AS name, COUNT(*) AS such_matches "
            "FROM players p "
            "JOIN bowled_in bw ON bw.player_id = p.id "
            "JOIN matches m ON m.id = bw.match_id "
            "WHERE m.format = 'Test' AND bw.runs_conceded >= 30 AND bw.wickets >= 1 "
            "GROUP BY p.id, p.name ORDER BY such_matches DESC LIMIT 10"
        ),
        "key_columns": ("name", "such_matches"),
        "ground_truth_note": "Test bowling with dual inequality constraints.",
    },
    {
        "name": "SQ_I07_karachi_allrounders",
        "question": "Which players both batted and bowled in matches played at Karachi? Show their total runs and wickets ordered by runs descending.",
        "query_class": "hard",
        "sql": (
            "SELECT p.name AS name, SUM(bi.runs) AS runs, SUM(bw.wickets) AS wickets "
            "FROM batted_in bi "
            "JOIN bowled_in bw ON bi.player_id = bw.player_id AND bi.match_id = bw.match_id "
            "JOIN players p ON p.id = bi.player_id "
            "JOIN matches m ON m.id = bi.match_id "
            "JOIN played_at pa ON pa.match_id = m.id "
            "JOIN venues v ON v.id = pa.venue_id "
            "WHERE v.city = 'Karachi' "
            "GROUP BY p.id, p.name ORDER BY runs DESC"
        ),
        "key_columns": ("name", "runs", "wickets"),
        "ground_truth_note": "Three-way join: batted + bowled + venue.",
    },
    {
        "name": "SQ_I08_pak_batting_by_format",
        "question": "For Pakistani players, what are the total runs, innings count, and average runs per innings in each format? Order by total runs descending.",
        "query_class": "hard",
        "sql": (
            "SELECT m.format AS format, SUM(bi.runs) AS total_runs, "
            "COUNT(*) AS innings_count, AVG(bi.runs) AS avg_runs "
            "FROM players p "
            "JOIN batted_in bi ON bi.player_id = p.id "
            "JOIN matches m ON m.id = bi.match_id "
            "WHERE p.country = 'PAK' "
            "GROUP BY m.format ORDER BY total_runs DESC"
        ),
        "key_columns": ("format", "total_runs", "innings_count", "avg_runs"),
        "ground_truth_note": "Multi-aggregate: SUM, COUNT, AVG in same projection.",
    },
    {
        "name": "SQ_I09_test_bowling_allrounders",
        "question": "Which players both batted and bowled in Test matches? Show their total wickets and runs, top 10 ordered by wickets then runs descending.",
        "query_class": "hard",
        "sql": (
            "SELECT p.name AS name, SUM(bw.wickets) AS wickets, SUM(bi.runs) AS runs "
            "FROM batted_in bi "
            "JOIN bowled_in bw ON bi.player_id = bw.player_id AND bi.match_id = bw.match_id "
            "JOIN players p ON p.id = bi.player_id "
            "JOIN matches m ON m.id = bi.match_id "
            "WHERE m.format = 'Test' "
            "GROUP BY p.id, p.name ORDER BY wickets DESC, runs DESC LIMIT 10"
        ),
        "key_columns": ("name", "wickets", "runs"),
        "ground_truth_note": "Multi-column ORDER BY with multi-pattern join.",
    },
    {
        "name": "SQ_I10_country_batting_stats",
        "question": "What are the total runs, innings count, and average runs per innings for players from each country? Order by total runs descending.",
        "query_class": "hard",
        "sql": (
            "SELECT p.country AS country, SUM(bi.runs) AS total_runs, "
            "COUNT(*) AS innings, AVG(bi.runs) AS avg_runs "
            "FROM players p JOIN batted_in bi ON bi.player_id = p.id "
            "GROUP BY p.country ORDER BY total_runs DESC"
        ),
        "key_columns": ("country", "total_runs", "innings", "avg_runs"),
        "ground_truth_note": "Country-level batting aggregate: SUM, COUNT, AVG.",
    },
    {
        "name": "SQ_I11_pak_batting_per_venue",
        "question": "How many runs did Pakistani players score and how many innings did they have at each venue? Order by runs descending.",
        "query_class": "hard",
        "sql": (
            "SELECT v.name AS venue, SUM(bi.runs) AS pak_runs, COUNT(*) AS innings "
            "FROM players p "
            "JOIN batted_in bi ON bi.player_id = p.id "
            "JOIN matches m ON m.id = bi.match_id "
            "JOIN played_at pa ON pa.match_id = m.id "
            "JOIN venues v ON v.id = pa.venue_id "
            "WHERE p.country = 'PAK' "
            "GROUP BY v.id, v.name ORDER BY pak_runs DESC"
        ),
        "key_columns": ("venue", "pak_runs", "innings"),
        "ground_truth_note": "2-hop multi-hop + country filter + multi-aggregate.",
    },
    {
        "name": "SQ_I12_t20_season_bowling",
        "question": "Who took the most T20 wickets per season? Show the top 10 ordered by wickets descending then season.",
        "query_class": "hard",
        "sql": (
            "SELECT m.season AS season, p.name AS name, SUM(bw.wickets) AS wickets "
            "FROM players p "
            "JOIN bowled_in bw ON bw.player_id = p.id "
            "JOIN matches m ON m.id = bw.match_id "
            "WHERE m.format = 'T20' "
            "GROUP BY m.season, p.id, p.name ORDER BY wickets DESC, season LIMIT 10"
        ),
        "key_columns": ("season", "name", "wickets"),
        "ground_truth_note": "T20 wickets grouped by (season, player).",
    },
]
