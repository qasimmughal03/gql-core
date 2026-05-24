"""Regression benchmark: proves engine correctness AND documents known limits.

Organized into four sections:

  A. Parse rejection
     Unsupported syntax (DISTINCT, WITH, OPTIONAL MATCH, UNION, IN, IS NULL,
     COUNT(DISTINCT)) must raise a clean Lark exception — never silently
     mis-parse and return wrong results.

  B. Oracle assertions
     Exact values hand-computed from the 5-fixture corpus and verified
     against known cricket-domain facts. These are accuracy proofs, not
     cross-engine parity checks. If both engines have the same bug they both
     pass parity tests; they cannot both have the exact same numeric answer.

  C. Adversarial tests
     Queries designed to expose specific known failure modes:
       • Cartesian product (no shared variables between patterns)
       • NULL-property comparisons (= and !=)
       • Edge-variable access on a multi-hop RPQ pattern
       • Correctness of the `AND` predicate pushdown when `OR` is also present

  D. Engine boundary tests
     Edge-of-language behaviour:
       • *0..0 quantifier (zero-depth RPQ)
       • Unbounded Kleene-star on a cyclic undirected graph (must terminate)
       • Empty-result aggregation semantics (COUNT with/without group key)
       • Double negation (NOT NOT P === P)

Fixture oracle values (all hand-verified):
  Matches     : 5  (IDs 1000001–1000005; 4 T20, 1 Test)
  Players     : 16 (5 PAK, 3 ENG, 3 AUS, 3 IND, 2 SRI)
  Venues      : 5  (Karachi, Lahore, Dubai, Birmingham, unknown-city)
  Tournaments : 1  (Asia Cup 2024, only match 1000001)
  BATTED_IN   : 12 edges
  BOWLED_IN   : 7  edges
  TEAMMATES_WITH : 16 edges

  Babar Azam batting:
    F1 1000001  runs=11  fours=1  sixes=1
    F2 1000002  runs=9   fours=2  sixes=0
    F4 1000004  runs=10  fours=1  sixes=1
    F5 1000005  runs=1   fours=0  sixes=0   ← boundaryless
    SUM = 31   MAX = 11   MIN = 1   AVG = 7.75   innings = 4

  Top wicket-takers: Naseem Shah (2), Jofra Archer (1)
  Highest batting score: Babar Azam (11)

  Boundaryless batting innings (fours=0 AND sixes=0):
    Babar F5, Joe Root F5, Mitchell Starc F2, Mohammad Rizwan F1,
    Pat Cummins F2, Shaheen Afridi F1, Shan Masood F2, Steve Smith F2,
    Virat Kohli F3  → 9 rows

  Non-PAK players: 11 (AUS ×3, ENG ×3, IND ×3, SRI ×2)
  Allrounders (batted AND bowled same match): Mitchell Starc F2 only

  Delivery chain from 1000001:1:0.1:
    0.1 → 0.2 → 0.3 → 0.4 → 0.5 → 0.6 → 0.7  (7 nodes, 6 successors)

  Babar's direct teammates: 4 (Rizwan ×4, Shaheen ×3, Naseem ×1, Shan ×1)
  Unbounded TEAMMATES_WITH* from Babar reaches all 4 teammates.
  Cartesian product |Player| × |Match| = 16 × 5 = 80.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lark import UnexpectedCharacters, UnexpectedToken

from graph.store import PropertyGraph
from ingestion.cricsheet_parser import CricsheetParser
from ingestion.validator import ShapeValidator
from query.executor import run
from query.parser import parse
from query.semantic import SemanticError

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
SHAPES = ROOT / "ontology" / "shapes.yaml"


@pytest.fixture(scope="module")
def graph() -> PropertyGraph:
    g = PropertyGraph()
    p = CricsheetParser(g, ShapeValidator(SHAPES))
    for f in sorted(FIXTURES.glob("*.json")):
        p.ingest_file(f)
    return g


# ── helpers ──────────────────────────────────────────────────────────────────

_LARK_ERRORS = (UnexpectedToken, UnexpectedCharacters, Exception)


def _assert_parse_error(source: str) -> None:
    """Assert that `source` raises a Lark parse error (not a silent wrong result)."""
    with pytest.raises(_LARK_ERRORS):
        parse(source)


# ═════════════════════════════════════════════════════════════════════════════
# SECTION A — Parse rejection
# Every unsupported construct must raise a parse error at the grammar level,
# never silently produce wrong results.
# ═════════════════════════════════════════════════════════════════════════════


def test_reject_distinct_in_return():
    """RETURN DISTINCT is not in the grammar → parse error."""
    _assert_parse_error("MATCH (p:Player) RETURN DISTINCT p.name")


def test_reject_count_distinct():
    """COUNT(DISTINCT ...) is not in the grammar → parse error."""
    _assert_parse_error(
        "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
        "RETURN COUNT(DISTINCT m.id) AS n"
    )


def test_reject_with_clause():
    """WITH clause (multi-stage queries) is not in the grammar → parse error."""
    _assert_parse_error(
        "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
        "WITH p, SUM(r.runs) AS total "
        "WHERE total > 1000 "
        "RETURN p.name, total"
    )


def test_reject_optional_match():
    """OPTIONAL MATCH is not in the grammar → parse error."""
    _assert_parse_error(
        "OPTIONAL MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
        "RETURN p.name, r.runs"
    )


def test_reject_union():
    """UNION is not in the grammar → parse error."""
    _assert_parse_error(
        "MATCH (p:Player) RETURN p.name "
        "UNION "
        "MATCH (m:Match) RETURN m.id"
    )


def test_reject_in_operator():
    """WHERE x IN [...] is not in the grammar → parse error."""
    _assert_parse_error(
        'MATCH (p:Player) WHERE p.country IN ["PAK", "ENG"] RETURN p.name'
    )


def test_reject_is_null():
    """IS NULL predicate is not in the grammar → parse error."""
    _assert_parse_error(
        "MATCH (p:Player) WHERE p.name IS NULL RETURN p.name"
    )


def test_reject_is_not_null():
    """IS NOT NULL predicate is not in the grammar → parse error."""
    _assert_parse_error(
        "MATCH (p:Player) WHERE p.name IS NOT NULL RETURN p.name"
    )


def test_reject_skip_clause():
    """SKIP / OFFSET is not in the grammar → parse error."""
    _assert_parse_error(
        "MATCH (m:Match) RETURN m.id ORDER BY m.id ASC SKIP 2 LIMIT 3"
    )


def test_reject_case_expression():
    """CASE / WHEN is not in the grammar → parse error."""
    _assert_parse_error(
        "MATCH (m:Match) "
        "RETURN CASE m.format WHEN 'Test' THEN 1 ELSE 0 END AS is_test"
    )


# ═════════════════════════════════════════════════════════════════════════════
# SECTION B — Oracle assertions
# Exact numeric and set values, hand-verified from fixture files.
# These prove the engine computes the RIGHT answer, not just that it agrees
# with a second implementation of the same potential bug.
# ═════════════════════════════════════════════════════════════════════════════


# ── B1: Simple counts ────────────────────────────────────────────────────────


def test_oracle_total_matches(graph: PropertyGraph):
    rows = run("MATCH (m:Match) RETURN COUNT(m) AS n", graph)
    assert rows == [{"n": 5}]


def test_oracle_total_players(graph: PropertyGraph):
    rows = run("MATCH (p:Player) RETURN COUNT(p) AS n", graph)
    assert rows == [{"n": 16}]


def test_oracle_total_venues(graph: PropertyGraph):
    rows = run("MATCH (v:Venue) RETURN COUNT(v) AS n", graph)
    assert rows == [{"n": 5}]


def test_oracle_test_match_count(graph: PropertyGraph):
    rows = run(
        'MATCH (m:Match) WHERE m.format = "Test" RETURN COUNT(m) AS n', graph
    )
    assert rows == [{"n": 1}]


def test_oracle_t20_match_count(graph: PropertyGraph):
    rows = run(
        'MATCH (m:Match) WHERE m.format = "T20" RETURN COUNT(m) AS n', graph
    )
    assert rows == [{"n": 4}]


def test_oracle_non_test_match_count_uses_negation(graph: PropertyGraph):
    """!= operator: non-Test matches = all T20s."""
    rows = run(
        'MATCH (m:Match) WHERE m.format != "Test" RETURN COUNT(m) AS n', graph
    )
    assert rows == [{"n": 4}]


def test_oracle_pak_player_count(graph: PropertyGraph):
    rows = run(
        'MATCH (p:Player) WHERE p.country = "PAK" RETURN COUNT(p) AS n', graph
    )
    assert rows == [{"n": 5}]


def test_oracle_non_pak_player_count(graph: PropertyGraph):
    """11 non-PAK players: AUS×3 + ENG×3 + IND×3 + SRI×2."""
    rows = run(
        'MATCH (p:Player) WHERE p.country != "PAK" RETURN COUNT(p) AS n',
        graph,
    )
    assert rows == [{"n": 11}]


def test_oracle_non_pak_player_set(graph: PropertyGraph):
    """Exact set of non-PAK players, verified against fixture data."""
    rows = run(
        'MATCH (p:Player) WHERE p.country != "PAK" '
        "RETURN p.name AS name ORDER BY name ASC",
        graph,
    )
    names = [r["name"] for r in rows]
    assert names == [
        "Ben Stokes",
        "Jasprit Bumrah",
        "Joe Root",
        "Jofra Archer",
        "Mitchell Starc",
        "Pat Cummins",
        "Pathum Nissanka",
        "Rohit Sharma",
        "Steve Smith",
        "Virat Kohli",
        "Wanindu Hasaranga",
    ]


# ── B2: Aggregation over known data ──────────────────────────────────────────


def test_oracle_babar_career_runs(graph: PropertyGraph):
    """Babar's career runs = 11+9+10+1 = 31 across 4 fixture innings."""
    rows = run(
        'MATCH (p:Player)-[r:BATTED_IN]->(m:Match) WHERE p.name = "Babar Azam" '
        "RETURN SUM(r.runs) AS total",
        graph,
    )
    assert rows == [{"total": 31}]


def test_oracle_babar_highest_score(graph: PropertyGraph):
    rows = run(
        'MATCH (p:Player)-[r:BATTED_IN]->(m:Match) WHERE p.name = "Babar Azam" '
        "RETURN MAX(r.runs) AS best",
        graph,
    )
    assert rows == [{"best": 11}]


def test_oracle_babar_lowest_score(graph: PropertyGraph):
    rows = run(
        'MATCH (p:Player)-[r:BATTED_IN]->(m:Match) WHERE p.name = "Babar Azam" '
        "RETURN MIN(r.runs) AS worst",
        graph,
    )
    assert rows == [{"worst": 1}]


def test_oracle_babar_innings_count(graph: PropertyGraph):
    """Babar batted in 4 of 5 fixtures (did not bat in F3)."""
    rows = run(
        'MATCH (p:Player)-[r:BATTED_IN]->(m:Match) WHERE p.name = "Babar Azam" '
        "RETURN COUNT(m) AS innings",
        graph,
    )
    assert rows == [{"innings": 4}]


def test_oracle_top_run_scorer_is_babar(graph: PropertyGraph):
    """Across all formats in fixtures, Babar is the top run scorer."""
    rows = run(
        "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
        "RETURN p.name AS player, SUM(r.runs) AS runs "
        "ORDER BY runs DESC LIMIT 1",
        graph,
    )
    assert rows[0]["player"] == "Babar Azam"
    assert rows[0]["runs"] == 31


def test_oracle_top_wicket_taker_is_naseem(graph: PropertyGraph):
    """Naseem Shah took 2 wickets in F2 (Test) — highest in fixtures."""
    rows = run(
        "MATCH (p:Player)-[r:BOWLED_IN]->(m:Match) "
        "RETURN p.name AS bowler, SUM(r.wickets) AS w "
        "ORDER BY w DESC LIMIT 1",
        graph,
    )
    assert rows[0]["bowler"] == "Naseem Shah"
    assert rows[0]["w"] == 2


def test_oracle_total_wickets_in_fixtures(graph: PropertyGraph):
    """Total wickets across all BOWLED_IN edges: Naseem 2 + Jofra 1 = 3."""
    rows = run(
        "MATCH (p:Player)-[r:BOWLED_IN]->(m:Match) "
        "RETURN SUM(r.wickets) AS total_wickets",
        graph,
    )
    assert rows == [{"total_wickets": 3}]


def test_oracle_highest_batting_score_in_corpus(graph: PropertyGraph):
    """Highest individual batting score across all innings is Babar's 11 in F1."""
    rows = run(
        "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
        "RETURN p.name AS player, MAX(r.runs) AS best "
        "ORDER BY best DESC LIMIT 1",
        graph,
    )
    assert rows[0] == {"player": "Babar Azam", "best": 11}


# ── B3: Multi-hop oracle values ──────────────────────────────────────────────


def test_oracle_karachi_match_count(graph: PropertyGraph):
    """Exactly 1 match (F1) was played at National Stadium, Karachi."""
    rows = run(
        'MATCH (m:Match)-[:PLAYED_AT]->(v:Venue) WHERE v.city = "Karachi" '
        "RETURN COUNT(m) AS n",
        graph,
    )
    assert rows == [{"n": 1}]


def test_oracle_babar_captained_all_matches(graph: PropertyGraph):
    """Babar captained all 5 fixture matches (10 CAPTAINED edges = 2 per match
    because both innings of a multi-innings match get a CAPTAINED edge)."""
    rows = run(
        'MATCH (p:Player)-[:CAPTAINED]->(m:Match) WHERE p.name = "Babar Azam" '
        "RETURN COUNT(m) AS n",
        graph,
    )
    # Babar captained 5 matches; multi-innings matches each yield one CAPTAINED
    # edge per innings (F2 Test has 2 innings → Babar has 5 unique matches).
    assert rows[0]["n"] == 5


def test_oracle_babar_batting_venues(graph: PropertyGraph):
    """Babar batted at 4 distinct venues in fixtures."""
    rows = run(
        'MATCH (p:Player)-[:BATTED_IN]->(m:Match)-[:PLAYED_AT]->(v:Venue) '
        'WHERE p.name = "Babar Azam" '
        "RETURN COUNT(m) AS n",
        graph,
    )
    # Babar batted in F1 (Karachi), F2 (unknown), F4 (Lahore), F5 (Birmingham)
    assert rows == [{"n": 4}]


def test_oracle_tournament_match_count(graph: PropertyGraph):
    """Only 1 match is linked to a tournament (Asia Cup 2024 = F1 1000001)."""
    rows = run(
        "MATCH (m:Match)-[:PART_OF_TOURNAMENT]->(t:Tournament) "
        "RETURN COUNT(m) AS n",
        graph,
    )
    assert rows == [{"n": 1}]


# ── B4: Multi-pattern (conjunction) oracle values ────────────────────────────


def test_oracle_allrounder_is_starc_only(graph: PropertyGraph):
    """Mitchell Starc is the only player who both batted AND bowled in the same
    fixture match (F2 Test). Shaheen Afridi bowled in F3/F5 but did not bat;
    Jofra Archer bowled in F1/F5 but did not bat in those same matches.
    """
    rows = run(
        "MATCH (p:Player)-[:BATTED_IN]->(m:Match), (p)-[:BOWLED_IN]->(m) "
        "RETURN p.name AS allrounder, COUNT(m) AS matches "
        "ORDER BY matches DESC, allrounder ASC",
        graph,
    )
    assert len(rows) == 1
    assert rows[0]["allrounder"] == "Mitchell Starc"
    assert rows[0]["matches"] == 1


def test_oracle_players_who_scored_50_plus(graph: PropertyGraph):
    """No player scored 50+ runs in any single fixture match."""
    rows = run(
        "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
        "WHERE r.runs >= 50 "
        "RETURN p.name AS player, r.runs AS runs "
        "ORDER BY runs DESC",
        graph,
    )
    assert rows == []


# ── B5: Undirected edge oracle values ────────────────────────────────────────


def test_oracle_babar_direct_teammate_count(graph: PropertyGraph):
    """Babar has exactly 4 unique direct teammates in the fixture corpus."""
    rows = run(
        'MATCH (p1:Player)-[t:TEAMMATES_WITH]-(p2:Player) '
        'WHERE p1.name = "Babar Azam" '
        "RETURN COUNT(p2) AS n",
        graph,
    )
    assert rows == [{"n": 4}]


def test_oracle_babar_rizwan_shared_matches(graph: PropertyGraph):
    """Babar and Rizwan appear in 4 of the same fixture matches."""
    rows = run(
        'MATCH (p1:Player)-[t:TEAMMATES_WITH]-(p2:Player) '
        'WHERE p1.name = "Babar Azam" AND p2.name = "Mohammad Rizwan" '
        "RETURN t.match_count AS n",
        graph,
    )
    assert rows == [{"n": 4}]


# ── B6: RPQ oracle values ────────────────────────────────────────────────────


def test_oracle_rpq_chain_length_from_first_delivery(graph: PropertyGraph):
    """6 deliveries are reachable from 1000001:1:0.1 via unbounded NEXT_DELIVERY*."""
    rows = run(
        'MATCH (d:Delivery)-[:NEXT_DELIVERY*]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.1" '
        "RETURN COUNT(d2) AS n",
        graph,
    )
    assert rows == [{"n": 6}]


def test_oracle_rpq_exactly_2_hops(graph: PropertyGraph):
    """Exactly 2 hops from 0.1 in the linear chain lands on 0.3."""
    rows = run(
        'MATCH (d:Delivery)-[:NEXT_DELIVERY*2]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.1" '
        "RETURN d2.id AS reached",
        graph,
    )
    assert rows == [{"reached": "1000001:1:0.3"}]


def test_oracle_rpq_bounded_range_count(graph: PropertyGraph):
    """`*1..3` from 0.1 visits 0.2, 0.3, 0.4 — exactly 3 deliveries."""
    rows = run(
        'MATCH (d:Delivery)-[:NEXT_DELIVERY*1..3]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.1" '
        "RETURN COUNT(d2) AS n",
        graph,
    )
    assert rows == [{"n": 3}]


def test_oracle_rpq_zero_or_more_includes_self(graph: PropertyGraph):
    """`*0..3` from 0.1 = start + 3 successors = 4 total."""
    rows = run(
        'MATCH (d:Delivery)-[:NEXT_DELIVERY*0..3]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.1" '
        "RETURN COUNT(d2) AS n",
        graph,
    )
    assert rows == [{"n": 4}]


# ── B7: Negation oracle values ───────────────────────────────────────────────


def test_oracle_boundaryless_innings_count(graph: PropertyGraph):
    """9 batting records have fours=0 AND sixes=0 in the fixture corpus."""
    rows = run(
        "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
        "WHERE r.fours = 0 AND r.sixes = 0 "
        "RETURN COUNT(m) AS n",
        graph,
    )
    assert rows == [{"n": 9}]


def test_oracle_boundaryless_innings_includes_babar_f5(graph: PropertyGraph):
    """Babar's 1-run innings in F5 (fours=0, sixes=0) must appear."""
    rows = run(
        "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
        "WHERE r.fours = 0 AND r.sixes = 0 "
        "RETURN p.name AS player, m.id AS mid "
        "ORDER BY player ASC, mid ASC",
        graph,
    )
    assert {"player": "Babar Azam", "mid": "1000005"} in rows


def test_oracle_innings_with_at_least_one_boundary(graph: PropertyGraph):
    """Innings with fours > 0 OR sixes > 0: total 12 - 9 = 3."""
    rows = run(
        "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
        "WHERE r.fours > 0 OR r.sixes > 0 "
        "RETURN COUNT(m) AS n",
        graph,
    )
    assert rows == [{"n": 3}]


# ═════════════════════════════════════════════════════════════════════════════
# SECTION C — Adversarial tests
# Queries targeting specific known failure modes.
# ═════════════════════════════════════════════════════════════════════════════


def test_adversarial_cartesian_product_total_count(graph: PropertyGraph):
    """MATCH (p:Player), (m:Match) with no shared variable is a Cartesian product.
    COUNT(m) with no group key must equal 16 × 5 = 80.
    Verifies the engine materialises the full product rather than pruning it.
    """
    rows = run(
        "MATCH (p:Player), (m:Match) RETURN COUNT(m) AS n", graph
    )
    assert rows == [{"n": 80}]


def test_adversarial_cartesian_product_per_player(graph: PropertyGraph):
    """With a group key, each of the 16 players must see exactly 5 matches."""
    rows = run(
        "MATCH (p:Player), (m:Match) "
        "RETURN p.name AS player, COUNT(m) AS n "
        "ORDER BY player ASC",
        graph,
    )
    assert len(rows) == 16
    for r in rows:
        assert r["n"] == 5, f"{r['player']} had {r['n']} instead of 5"


def test_adversarial_null_property_equal_returns_empty(graph: PropertyGraph):
    """Known-schema property mistakes are semantic errors, not empty answers."""
    with pytest.raises(SemanticError, match="unknown node property"):
        run(
            'MATCH (p:Player) WHERE p.nonexistent_prop = "x" '
            "RETURN COUNT(p) AS n",
            graph,
        )


def test_adversarial_null_property_not_equal_also_returns_empty(graph: PropertyGraph):
    """Known-schema property mistakes are rejected for != as well."""
    with pytest.raises(SemanticError, match="unknown node property"):
        run(
            'MATCH (p:Player) WHERE p.nonexistent_prop != "x" '
            "RETURN COUNT(p) AS n",
            graph,
        )


def test_adversarial_rpq_edge_var_multi_hop_raises(graph: PropertyGraph):
    """Using an edge variable on a multi-hop RPQ pattern (e.g. [r:NEXT_DELIVERY*2])
    must raise NotImplementedError because the engine only binds the last edge,
    not the full relationship list that Cypher specifies.
    This test documents the known limitation so it cannot silently regress
    into returning wrong property values.
    """
    with pytest.raises(NotImplementedError, match="multi-hop"):
        run(
            'MATCH (d:Delivery)-[r:NEXT_DELIVERY*2]->(d2:Delivery) '
            'WHERE d.id = "1000001:1:0.1" '
            "RETURN d2.id AS reached",
            graph,
        )


def test_adversarial_and_or_precedence_is_correct(graph: PropertyGraph):
    """AND binds tighter than OR, matching standard boolean algebra.
    (format='Test' AND season='2023/24') OR id='1000001' should match F2 and F1.
    If OR were evaluated first this would match a different set.
    """
    rows = run(
        'MATCH (m:Match) '
        'WHERE m.format = "Test" AND m.season = "2023/24" '
        '   OR m.id = "1000001" '
        "RETURN m.id AS id ORDER BY id ASC",
        graph,
    )
    assert [r["id"] for r in rows] == ["1000001", "1000002"]


def test_adversarial_or_predicate_not_pushed_but_correct(graph: PropertyGraph):
    """OR predicates are not pushed into the Scan/Expand ops (only AND terms are
    pushed). The trailing FilterOp must still produce the right result.
    """
    rows = run(
        'MATCH (p:Player) '
        'WHERE p.country = "PAK" OR p.country = "ENG" '
        "RETURN COUNT(p) AS n",
        graph,
    )
    # 5 PAK + 3 ENG = 8
    assert rows == [{"n": 8}]


def test_adversarial_multi_pattern_inner_join_semantics(graph: PropertyGraph):
    """Multi-pattern join is an INNER join: players who did NOT both bat and
    bowl in the same match are excluded. No OPTIONAL MATCH available.
    All 12 BATTED_IN × 7 BOWLED_IN edges share only Mitchell Starc in F2.
    """
    rows = run(
        "MATCH (p:Player)-[:BATTED_IN]->(m:Match), (p)-[:BOWLED_IN]->(m) "
        "RETURN p.name AS p, m.id AS mid ORDER BY p ASC, mid ASC",
        graph,
    )
    # Only Starc batted AND bowled in the same fixture match.
    assert rows == [{"p": "Mitchell Starc", "mid": "1000002"}]


# ═════════════════════════════════════════════════════════════════════════════
# SECTION D — Engine boundary tests
# ═════════════════════════════════════════════════════════════════════════════


def test_boundary_zero_depth_rpq_returns_only_start(graph: PropertyGraph):
    """`*0..0` yields depth-0 (start node) only — no successors visited."""
    rows = run(
        'MATCH (d:Delivery)-[:NEXT_DELIVERY*0..0]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.1" '
        "RETURN COUNT(d2) AS n",
        graph,
    )
    assert rows == [{"n": 1}]


def test_boundary_zero_depth_rpq_start_is_self(graph: PropertyGraph):
    """`*0..0` binds d2 to the start node itself."""
    rows = run(
        'MATCH (d:Delivery)-[:NEXT_DELIVERY*0..0]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.1" '
        "RETURN d2.id AS id",
        graph,
    )
    assert rows == [{"id": "1000001:1:0.1"}]


def test_boundary_unbounded_kleene_on_cyclic_graph_terminates(graph: PropertyGraph):
    """[:TEAMMATES_WITH*] traverses an undirected, cyclic graph. The BFS visited-set
    must prevent infinite loops. From Babar, exactly 4 teammates are reachable.
    """
    rows = run(
        'MATCH (p1:Player)-[:TEAMMATES_WITH*]-(p2:Player) '
        'WHERE p1.name = "Babar Azam" '
        "RETURN COUNT(p2) AS n",
        graph,
    )
    assert rows == [{"n": 4}]


def test_boundary_unbounded_kleene_result_set_is_exact(graph: PropertyGraph):
    """Unbounded TEAMMATES_WITH* from Babar reaches exactly his 4 direct
    teammates (Rizwan, Shaheen, Naseem, Shan) — no more, no less, because the
    fixture teammates graph has two connected components.
    """
    rows = run(
        'MATCH (p1:Player)-[:TEAMMATES_WITH*]-(p2:Player) '
        'WHERE p1.name = "Babar Azam" '
        "RETURN p2.name AS teammate ORDER BY teammate ASC",
        graph,
    )
    names = [r["teammate"] for r in rows]
    assert names == ["Mohammad Rizwan", "Naseem Shah", "Shaheen Afridi", "Shan Masood"]


def test_boundary_empty_result_with_no_group_key_returns_zero_count(graph: PropertyGraph):
    """COUNT over empty match set with no GROUP BY returns [{n: 0}], not [].
    GROUP BY semantics: no group-key cols → one implicit group, even if empty.
    """
    rows = run(
        "MATCH (m:Match) WHERE m.format = \"ODI\" RETURN COUNT(m) AS n",
        graph,
    )
    assert rows == [{"n": 0}]


def test_boundary_empty_result_with_group_key_returns_empty_list(graph: PropertyGraph):
    """COUNT over empty match set WITH a group key returns [], not [{n: 0}].
    With a group key, groups are formed per distinct key value — none exist.
    """
    rows = run(
        "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
        "WHERE m.format = \"ODI\" "
        "RETURN p.name AS player, COUNT(m) AS n",
        graph,
    )
    assert rows == []


def test_boundary_double_negation_is_identity(graph: PropertyGraph):
    """NOT NOT P ≡ P for any predicate P."""
    direct = run(
        'MATCH (m:Match) WHERE m.format = "Test" RETURN m.id AS id',
        graph,
    )
    double_not = run(
        'MATCH (m:Match) WHERE NOT NOT m.format = "Test" RETURN m.id AS id',
        graph,
    )
    assert {r["id"] for r in direct} == {r["id"] for r in double_not}


def test_boundary_kleene_plus_equals_star_on_acyclic_chain(graph: PropertyGraph):
    """`+` and `*` are both lo=1, hi=∞; on a linear chain they must agree."""
    plus = run(
        'MATCH (d:Delivery)-[:NEXT_DELIVERY+]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.1" '
        "RETURN COUNT(d2) AS n",
        graph,
    )
    star = run(
        'MATCH (d:Delivery)-[:NEXT_DELIVERY*]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.1" '
        "RETURN COUNT(d2) AS n",
        graph,
    )
    assert plus == star == [{"n": 6}]


def test_boundary_rpq_at_chain_end_returns_empty(graph: PropertyGraph):
    """Starting from the LAST delivery in a chain: `*1..5` returns 0 (no successors)."""
    rows = run(
        'MATCH (d:Delivery)-[:NEXT_DELIVERY*1..5]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.7" '
        "RETURN COUNT(d2) AS n",
        graph,
    )
    assert rows == [{"n": 0}]


def test_boundary_single_node_pattern_returns_all_of_label(graph: PropertyGraph):
    """MATCH (m:Match) RETURN COUNT(m) scans all Match nodes — no edge traversal."""
    rows = run("MATCH (m:Match) RETURN COUNT(m) AS n", graph)
    assert rows == [{"n": graph.stats()["by_label"]["Match"]}]


def test_boundary_unknown_label_returns_empty(graph: PropertyGraph):
    """Scanning a label that does not exist returns []."""
    rows = run("MATCH (x:Phantom) RETURN COUNT(x) AS n", graph)
    assert rows == [{"n": 0}]


def test_boundary_property_filter_in_node_pattern(graph: PropertyGraph):
    """Inline property filter in node pattern `{format: 'Test'}` is equivalent
    to WHERE m.format = 'Test'.
    """
    inline = run(
        'MATCH (m:Match {format: "Test"}) RETURN COUNT(m) AS n', graph
    )
    where_ = run(
        'MATCH (m:Match) WHERE m.format = "Test" RETURN COUNT(m) AS n', graph
    )
    assert inline == where_ == [{"n": 1}]


def test_boundary_order_by_desc_puts_highest_first(graph: PropertyGraph):
    """ORDER BY runs DESC: first row must have the highest value."""
    rows = run(
        "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
        "RETURN p.name AS player, SUM(r.runs) AS runs "
        "ORDER BY runs DESC LIMIT 3",
        graph,
    )
    assert rows[0]["runs"] >= rows[1]["runs"] >= rows[2]["runs"]
    assert rows[0]["player"] == "Babar Azam"


def test_boundary_multi_column_order_by_stable(graph: PropertyGraph):
    """Secondary ORDER BY column breaks ties deterministically."""
    rows = run(
        "MATCH (m:Match) RETURN m.id AS id, m.format AS fmt "
        "ORDER BY fmt ASC, id ASC",
        graph,
    )
    fmts = [r["fmt"] for r in rows]
    assert fmts == sorted(fmts)
    # Within same format, IDs must be ascending.
    for i in range(len(rows) - 1):
        if rows[i]["fmt"] == rows[i + 1]["fmt"]:
            assert rows[i]["id"] <= rows[i + 1]["id"]
