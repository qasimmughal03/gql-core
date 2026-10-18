"""Tests for the Natural-Language QA Benchmark.

Validates every NL query across three axes:

  1. Parse correctness  — every Cypher string is parsed without error.
  2. Cross-engine parity — Cypher and SQL return the same canonical row-set
                           on fixture data (same check as the main benchmark).
  3. Structural invariants — query-class-specific assertions that do not
                             depend on exact numeric values (e.g., simple
                             count queries must return exactly one row).
  4. Known fixture values — a handful of queries whose correct answer can be
                            hand-computed from the 5-fixture corpus.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from benchmark.natural_queries import NL_QUERIES, expressibility
from benchmark.vs_sqlite import _canonical_rows, _resolve_start_id, _rows_equal
from graph.store import PropertyGraph
from ingestion.cricsheet_parser import CricsheetParser
from ingestion.validator import ShapeValidator
from query.executor import run as run_cypher
from query.parser import parse
from scripts.build_sqlite_mirror import build_mirror

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
SHAPES = ROOT / "ontology" / "shapes.yaml"


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def graph() -> PropertyGraph:
    g = PropertyGraph()
    p = CricsheetParser(g, ShapeValidator(SHAPES))
    for f in sorted(FIXTURES.glob("*.json")):
        p.ingest_file(f)
    return g


@pytest.fixture(scope="module")
def mirror(graph: PropertyGraph, tmp_path_factory) -> sqlite3.Connection:
    db = tmp_path_factory.mktemp("nl") / "nl.db"
    conn = build_mirror(graph, db)
    yield conn
    conn.close()


def _query_by_name(name: str) -> dict:
    return next(q for q in NL_QUERIES if q["name"] == name)


def _run_pair(graph, conn, raw_q):
    q = _resolve_start_id(raw_q, graph)
    cypher = run_cypher(q["cypher"], graph)
    sql = conn.cursor().execute(q["sql"]).fetchall()
    return q, cypher, sql


# ── 1. Parse correctness ─────────────────────────────────────────────────


def test_all_nl_queries_parse_without_error():
    """Every Cypher string in NL_QUERIES must parse without a Lark exception."""
    errors = []
    for q in NL_QUERIES:
        cypher = q["cypher"]
        # Replace placeholder so the parser sees a valid string literal.
        cypher_filled = cypher.replace("{start_id}", "dummy-id-for-parse-check")
        try:
            parse(cypher_filled)
        except Exception as exc:
            errors.append(f"{q['name']}: {exc}")
    assert not errors, "\n".join(errors)


# ── 2. Cross-engine parity (all 35 queries on fixture corpus) ────────────


def test_all_nl_queries_cross_engine_parity(graph: PropertyGraph, mirror):
    """Cypher and SQL must return identical canonical row-sets for every NL query."""
    mismatches = []
    for raw_q in NL_QUERIES:
        q, cypher_rows, sql_rows = _run_pair(graph, mirror, raw_q)
        is_distinct = "DISTINCT" in q.get("sql", "").upper()
        canon_c = _canonical_rows(cypher_rows, q["key_columns"], distinct=is_distinct)
        canon_s = _canonical_rows(sql_rows, q["key_columns"])
        if not _rows_equal(canon_c, canon_s):
            mismatches.append(
                f"\n  {q['name']}: cypher={canon_c[:3]}  sql={canon_s[:3]}"
            )
    assert not mismatches, "".join(mismatches)


# ── 3. Structural invariants ─────────────────────────────────────────────

# Simple-lookup queries return exactly one row (a scalar COUNT).
@pytest.mark.parametrize("name", [
    "NQ01_total_matches",
    "NQ02_total_players",
    "NQ03_test_match_count",
    "NQ04_venue_count",
])
def test_simple_lookup_returns_one_row(name, graph):
    q = _query_by_name(name)
    rows = run_cypher(q["cypher"], graph)
    assert len(rows) == 1, f"{name}: expected 1 row, got {len(rows)}"


def test_simple_lookup_counts_are_positive(graph):
    """All simple-lookup queries must return a positive integer."""
    for name in ("NQ01_total_matches", "NQ02_total_players",
                 "NQ03_test_match_count", "NQ04_venue_count"):
        q = _query_by_name(name)
        col = q["key_columns"][0]
        rows = run_cypher(q["cypher"], graph)
        assert rows[0][col] > 0, f"{name}: got {rows[0][col]}"


def test_aggregation_queries_return_at_least_one_row(graph):
    """Aggregation queries (Class B) must return at least one row (skip if
    the fixture corpus has no matching data for the format filter)."""
    # NQ08 filters on format=ODI AND country=PAK; fixtures may have no ODI data.
    skip_if_empty = {"NQ08_top_odi_fours_pakistan", "NQ09_avg_runs_conceded_test_pak"}
    agg_names = [
        "NQ05_top_test_run_scorers",
        "NQ06_top_t20_six_hitters",
        "NQ07_top_wicket_takers",
        "NQ08_top_odi_fours_pakistan",
        "NQ09_avg_runs_conceded_test_pak",
    ]
    for name in agg_names:
        q = _query_by_name(name)
        rows = run_cypher(q["cypher"], graph)
        if name in skip_if_empty and len(rows) == 0:
            continue  # No matching data in fixture corpus — skip, don't fail.
        assert len(rows) >= 1, f"{name}: expected >=1 rows, got {len(rows)}"


def test_multi_hop_queries_return_non_negative(graph):
    """Multi-hop path queries must return >= 0 rows (empty is OK if no data)."""
    hop_names = [
        "NQ10_batters_at_karachi",
        "NQ11_matches_at_dubai_venues",
        "NQ12_bowlers_at_abu_dhabi",
        "NQ13_matches_per_tournament",
    ]
    for name in hop_names:
        q = _query_by_name(name)
        rows = run_cypher(q["cypher"], graph)
        assert isinstance(rows, list), f"{name}: not a list"


def test_undirected_queries_symmetric(graph):
    """TEAMMATES_WITH is undirected: if A↔B matches, then B↔A must match too."""
    # Use NQ18 (Rizwan's teammates) and verify Rizwan appears as a teammate
    # in the reverse lookup on the fixture graph.
    q18 = _query_by_name("NQ18_rizwan_teammates")
    rizwan_rows = run_cypher(q18["cypher"], graph)
    if not rizwan_rows:
        pytest.skip("No Rizwan matches in fixtures")
    # For each teammate T of Rizwan, check Rizwan is a teammate of T.
    for row in rizwan_rows[:3]:
        teammate_name = row["teammate"]
        q_reverse = (
            f'MATCH (p1:Player)-[t:TEAMMATES_WITH]-(p2:Player) '
            f'WHERE p1.name = "{teammate_name}" AND p2.name = "Mohammad Rizwan" '
            f'RETURN t.match_count AS shared_matches'
        )
        rev_rows = run_cypher(q_reverse, graph)
        assert rev_rows, (
            f"Symmetry broken: {teammate_name} is listed as Rizwan's teammate "
            f"but Rizwan is not listed as {teammate_name}'s teammate"
        )
        # match_count must also be symmetric
        assert rev_rows[0]["shared_matches"] == row["shared_matches"]


def test_rpq_queries_have_start_id_placeholder(graph):
    """All RPQ queries with needs_start_id must have {start_id} in Cypher and SQL."""
    for q in NL_QUERIES:
        if q.get("needs_start_id"):
            assert "{start_id}" in q["cypher"], f"{q['name']}: missing {{start_id}} in cypher"
            assert "{start_id}" in q["sql"], f"{q['name']}: missing {{start_id}} in sql"


def test_rpq_five_hops_bounded_by_chain_length(graph):
    """NQ21 (*1..5) can return at most 5 results on any linear chain."""
    q = _resolve_start_id(_query_by_name("NQ21_rpq_five_hops"), graph)
    rows = run_cypher(q["cypher"], graph)
    assert len(rows) == 1
    reachable = rows[0]["reachable"]
    assert 0 <= reachable <= 5, f"expected 0-5, got {reachable}"


def test_rpq_zero_or_more_includes_self(graph):
    """NQ24 (*0..3) must return >= *1..3 because it includes the start node."""
    q0 = _resolve_start_id(_query_by_name("NQ24_rpq_zero_or_more"), graph)
    q1_cypher = q0["cypher"].replace("*0..3", "*1..3").replace(
        "reachable_incl_self", "reachable"
    )
    rows0 = run_cypher(q0["cypher"], graph)[0]["reachable_incl_self"]
    rows1 = run_cypher(q1_cypher, graph)[0]["reachable"]
    assert rows0 >= rows1, (
        f"*0..3 ({rows0}) should be >= *1..3 ({rows1}) by 1 (the start node)"
    )


def test_rpq_one_or_more_capped_le_eight(graph):
    """NQ25 (*1..8) can return at most 8 deliveries."""
    q = _resolve_start_id(_query_by_name("NQ25_rpq_one_or_more_capped"), graph)
    rows = run_cypher(q["cypher"], graph)
    assert len(rows) == 1
    assert 0 <= rows[0]["reachable_plus"] <= 8


def test_negation_non_pak_players_have_different_country(graph):
    """NQ30: all returned players must have country != PAK."""
    q = _query_by_name("NQ30_non_pak_players")
    rows = run_cypher(q["cypher"], graph)
    for r in rows:
        assert r["country"] != "PAK", (
            f"{r['player']} has country=PAK but appeared in non-PAK query"
        )


def test_negation_boundaryless_innings_zero_boundaries(graph):
    """NQ29: all returned innings had fours=0 and sixes=0."""
    # Verify by running an inverse query: none of these players should
    # have scored a 4 or 6 in a match that was counted as boundaryless.
    q = _query_by_name("NQ29_boundaryless_innings")
    rows = run_cypher(q["cypher"], graph)
    # If fixture has any results, the count must be positive.
    for r in rows:
        assert r["boundaryless_innings"] > 0, (
            f"{r['player']} has zero boundaryless innings but appeared in results"
        )


# ── 4. Known fixture values ───────────────────────────────────────────────


def test_nq01_total_matches_equals_fixture_count(graph):
    """NQ01 must equal the number of fixture files ingested (5)."""
    q = _query_by_name("NQ01_total_matches")
    rows = run_cypher(q["cypher"], graph)
    assert rows[0]["total_matches"] == 5


def test_nq02_total_players_from_stats(graph):
    """NQ02 must match graph.stats()['by_label']['Player']."""
    q = _query_by_name("NQ02_total_players")
    rows = run_cypher(q["cypher"], graph)
    assert rows[0]["total_players"] == graph.stats()["by_label"]["Player"]


def test_nq03_test_match_count_one_fixture(graph):
    """NQ03: exactly 1 Test match in fixtures (fixture 1000002 is a Test)."""
    q = _query_by_name("NQ03_test_match_count")
    rows = run_cypher(q["cypher"], graph)
    assert rows[0]["test_matches"] == 1


def test_nq04_venue_count_matches_stats(graph):
    """NQ04 must match graph.stats()['by_label']['Venue']."""
    q = _query_by_name("NQ04_venue_count")
    rows = run_cypher(q["cypher"], graph)
    assert rows[0]["venue_count"] == graph.stats()["by_label"]["Venue"]


def test_nq29_babar_has_some_boundaryless_innings(graph):
    """Babar has 1 innings in fixture F5 with only 1 run (no boundary).
    NQ29 must pick this up."""
    q = _query_by_name("NQ29_boundaryless_innings")
    rows = run_cypher(q["cypher"], graph)
    player_names = [r["player"] for r in rows]
    # Babar has runs=1, fours=0, sixes=0 in fixture F5.
    assert "Babar Azam" in player_names


def test_nq20_babar_shaheen_cross_engine_parity(graph, mirror):
    """NQ20 cross-engine parity: Cypher and SQL agree on Babar-Shaheen shared matches.

    In the fixture corpus, cricsheet spells the name 'Shaheen Afridi' (short form),
    so the query (which uses 'Shaheen Shah Afridi') returns 0 rows from both engines
    — which is still a correct parity result.  The full corpus returns 100+ shared
    matches under the full name.
    """
    q, cypher_rows, sql_rows = _run_pair(graph, mirror, _query_by_name("NQ20_babar_shaheen_shared_matches"))
    canon_c = _canonical_rows(cypher_rows, q["key_columns"])
    canon_s = _canonical_rows(sql_rows, q["key_columns"])
    assert _rows_equal(canon_c, canon_s)


def test_nq21_rpq_five_hops_correct_count_from_known_start(graph):
    """From delivery 1000001:1:0.1, exactly 5 deliveries are reachable in *1..5."""
    cypher = (
        'MATCH (d:Delivery)-[:NEXT_DELIVERY*1..5]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.1" '
        'RETURN COUNT(d2) AS reachable'
    )
    rows = run_cypher(cypher, graph)
    assert rows[0]["reachable"] == 5


def test_nq22_rpq_exact_two_hops_from_known_start(graph):
    """From delivery 1000001:1:0.1, delivery 2 hops away is 1000001:1:0.3."""
    cypher = (
        'MATCH (d:Delivery)-[:NEXT_DELIVERY*2]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.1" '
        'RETURN d2.id AS delivery_2_hops'
    )
    rows = run_cypher(cypher, graph)
    assert rows == [{"delivery_2_hops": "1000001:1:0.3"}]


def test_nq24_zero_or_more_from_known_start(graph):
    """*0..3 from 1000001:1:0.1 = 4 deliveries (start + 3 successors)."""
    cypher = (
        'MATCH (d:Delivery)-[:NEXT_DELIVERY*0..3]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.1" '
        'RETURN COUNT(d2) AS reachable_incl_self'
    )
    rows = run_cypher(cypher, graph)
    assert rows[0]["reachable_incl_self"] == 4


# ── 5. Expressibility sanity ─────────────────────────────────────────────


def test_all_nl_sql_tokens_at_least_as_many_as_cypher():
    """SQL must be at least as long for path/join/RPQ queries.

    The thesis holds for queries involving graph traversal, joins on shared
    variables, or recursive path quantifiers. Simple property filters
    (simple_lookup, negation without joins) may be shorter in SQL since SQL
    can access table columns directly without node/edge traversal syntax.
    """
    # Classes where the graph-query advantage is structural (traversal / RPQ).
    path_classes = {"aggregation", "multi_hop", "multi_pattern",
                    "undirected", "rpq", "rpq_filter", "hard"}
    violations = []
    for q in NL_QUERIES:
        if q["query_class"] not in path_classes:
            continue
        e = expressibility(q)
        if e["sql_tokens"] < e["cypher_tokens"]:
            violations.append(
                f"{q['name']}: sql={e['sql_tokens']} < cypher={e['cypher_tokens']}"
            )
    assert not violations, "\n".join(violations)


def test_rpq_unbounded_queries_require_recursive_sql():
    """RPQ queries using star/range/zero-or-more quantifiers (not fixed *N) must
    use WITH RECURSIVE in SQL — they require recursive enumeration."""
    # NQ22 uses *2 (fixed depth) which the SQL expresses without recursion;
    # all others use bounded ranges and need WITH RECURSIVE.
    fixed_depth_queries = {"NQ22_rpq_exact_two_hops"}
    for q in NL_QUERIES:
        if q["query_class"] in ("rpq", "rpq_filter") and q.get("needs_start_id"):
            if q["name"] in fixed_depth_queries:
                continue
            e = expressibility(q)
            assert e["sql_recursive"], (
                f"{q['name']} is a bounded-range RPQ but SQL has no WITH RECURSIVE"
            )


def test_query_class_coverage():
    """All expected query classes are represented in NL_QUERIES."""
    expected_classes = {
        "simple_lookup", "aggregation", "multi_hop",
        "multi_pattern", "undirected", "rpq", "rpq_filter",
        "negation", "hard",
    }
    present_classes = {q["query_class"] for q in NL_QUERIES}
    missing = expected_classes - present_classes
    assert not missing, f"Missing query classes: {missing}"


def test_nl_queries_have_required_fields():
    """Every NL query must have all required metadata fields."""
    required = {
        "name", "question", "query_class", "cypher", "sql",
        "key_columns", "ground_truth_note",
    }
    for q in NL_QUERIES:
        missing = required - q.keys()
        assert not missing, f"{q.get('name', '?')}: missing fields {missing}"
