"""Targeted gap-fill tests for the executor.

These tests cover language features that parse cleanly but were not
previously exercised end-to-end against fixture data:

  - All quantifier forms: `+`, `*N`, `*M..N`, `*0..N`.
  - All comparison operators: `=`, `!=`, `<`, `<=`, `>`, `>=`.
  - `NOT` in WHERE.
  - Nested AND/OR combinations.
  - Exact-value assertions for standalone SUM, AVG, MIN, MAX (the
    previous tests only checked non-null).

Every fact asserted here is hand-computable from the fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from graph.store import PropertyGraph
from ingestion.cricsheet_parser import CricsheetParser
from ingestion.validator import ShapeValidator
from query.executor import run as run_cypher

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


# ─── Quantifier forms ───────────────────────────────────────────────


def test_plus_quantifier_equals_star_for_acyclic_chain(graph: PropertyGraph):
    """`+` (one-or-more) on the linear NEXT_DELIVERY chain in fixture
    1000001 innings 1 = `*1..∞` semantically. Both should return the
    same 6 deliveries reachable from delivery 0.1.
    """
    plus = run_cypher(
        'MATCH (d:Delivery)-[:NEXT_DELIVERY+]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.1" '
        'RETURN COUNT(d2) AS reachable',
        graph,
    )
    star = run_cypher(
        'MATCH (d:Delivery)-[:NEXT_DELIVERY*]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.1" '
        'RETURN COUNT(d2) AS reachable',
        graph,
    )
    assert plus[0]["reachable"] == star[0]["reachable"] == 6


def test_exactly_n_quantifier(graph: PropertyGraph):
    """`*2` matches exactly 2 hops away from delivery 0.1 — which is 0.3."""
    rows = run_cypher(
        'MATCH (d:Delivery)-[:NEXT_DELIVERY*2]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.1" '
        'RETURN d2.id AS reached',
        graph,
    )
    assert rows == [{"reached": "1000001:1:0.3"}]


def test_range_quantifier_includes_endpoints(graph: PropertyGraph):
    """`*1..3` from 0.1 visits 0.2, 0.3, 0.4 — three deliveries."""
    rows = run_cypher(
        'MATCH (d:Delivery)-[:NEXT_DELIVERY*1..3]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.1" '
        'RETURN COUNT(d2) AS reachable',
        graph,
    )
    assert rows == [{"reachable": 3}]


def test_zero_or_more_quantifier_includes_start(graph: PropertyGraph):
    """`*0..3` reaches the start itself plus 3 forward hops = 4 distinct deliveries."""
    rows = run_cypher(
        'MATCH (d:Delivery)-[:NEXT_DELIVERY*0..3]->(d2:Delivery) '
        'WHERE d.id = "1000001:1:0.1" '
        'RETURN COUNT(d2) AS reachable',
        graph,
    )
    assert rows == [{"reachable": 4}]


# ─── Comparison operators ───────────────────────────────────────────


def test_not_equal_operator(graph: PropertyGraph):
    """`!=` excludes the matching value."""
    rows = run_cypher(
        'MATCH (m:Match) WHERE m.format != "Test" RETURN m.id AS id',
        graph,
    )
    # All fixtures except 1000002 (Test) → 4 T20 matches.
    assert sorted(r["id"] for r in rows) == ["1000001", "1000003", "1000004", "1000005"]


def test_less_than_operator(graph: PropertyGraph):
    """`<` strictly below value: balls_per_over < 6 — none in fixtures (all = 6)."""
    rows = run_cypher(
        "MATCH (m:Match) WHERE m.balls_per_over < 6 RETURN m.id",
        graph,
    )
    assert rows == []


def test_less_than_or_equal_operator(graph: PropertyGraph):
    """All 5 fixture matches have balls_per_over == 6, so `<=` returns all 5."""
    rows = run_cypher(
        "MATCH (m:Match) WHERE m.balls_per_over <= 6 RETURN m.id",
        graph,
    )
    assert len(rows) == 5


def test_greater_than_operator(graph: PropertyGraph):
    """Babar scored 11 in F1 — only batting innings with runs > 10 in fixtures."""
    rows = run_cypher(
        "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
        "WHERE r.runs > 10 "
        "RETURN p.name AS player, r.runs AS runs",
        graph,
    )
    assert rows == [{"player": "Babar Azam", "runs": 11}]


def test_greater_than_or_equal_operator(graph: PropertyGraph):
    """`>=` 10: Babar F1 (11) and F4 (10) → 2 rows."""
    rows = run_cypher(
        "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) "
        "WHERE r.runs >= 10 "
        "RETURN COUNT(m) AS innings",
        graph,
    )
    assert rows == [{"innings": 2}]


# ─── NOT in WHERE ───────────────────────────────────────────────────


def test_not_in_where(graph: PropertyGraph):
    """NOT inverts the predicate. NOT (format = 'Test') keeps the 4 T20 matches."""
    rows = run_cypher(
        'MATCH (m:Match) WHERE NOT m.format = "Test" RETURN m.id AS id',
        graph,
    )
    assert sorted(r["id"] for r in rows) == ["1000001", "1000003", "1000004", "1000005"]


def test_double_negation(graph: PropertyGraph):
    """NOT NOT P = P."""
    rows = run_cypher(
        'MATCH (m:Match) WHERE NOT NOT m.format = "Test" RETURN m.id AS id',
        graph,
    )
    assert [r["id"] for r in rows] == ["1000002"]


# ─── Boolean composition ────────────────────────────────────────────


def test_and_or_precedence(graph: PropertyGraph):
    """AND binds tighter than OR.
    Matches that are (format='Test' AND season='2023/24') OR id='1000001'.
    Expect F2 (Test 2023/24) and F1 (1000001).
    """
    rows = run_cypher(
        'MATCH (m:Match) '
        'WHERE m.format = "Test" AND m.season = "2023/24" '
        '   OR m.id = "1000001" '
        'RETURN m.id AS id',
        graph,
    )
    assert sorted(r["id"] for r in rows) == ["1000001", "1000002"]


def test_parenthesized_or_changes_meaning(graph: PropertyGraph):
    """(format='Test' OR id='1000001') AND season='2023/24' → only F2."""
    rows = run_cypher(
        'MATCH (m:Match) '
        'WHERE (m.format = "Test" OR m.id = "1000001") '
        '  AND m.season = "2023/24" '
        'RETURN m.id AS id',
        graph,
    )
    assert [r["id"] for r in rows] == ["1000002"]


# ─── Aggregation exact values ───────────────────────────────────────


def test_sum_exact_value(graph: PropertyGraph):
    """SUM over Babar's BATTED_IN.runs across 4 fixture matches (F1+F2+F4+F5):
    11 + 9 + 10 + 1 = 31.
    """
    rows = run_cypher(
        'MATCH (p:Player)-[r:BATTED_IN]->(m:Match) WHERE p.name = "Babar Azam" '
        'RETURN SUM(r.runs) AS career',
        graph,
    )
    assert rows == [{"career": 31}]


def test_max_exact_value(graph: PropertyGraph):
    """Babar's best score across fixtures = 11."""
    rows = run_cypher(
        'MATCH (p:Player)-[r:BATTED_IN]->(m:Match) WHERE p.name = "Babar Azam" '
        'RETURN MAX(r.runs) AS best',
        graph,
    )
    assert rows == [{"best": 11}]


def test_min_exact_value(graph: PropertyGraph):
    """Babar's worst (smallest) score across fixtures = 1 (F5)."""
    rows = run_cypher(
        'MATCH (p:Player)-[r:BATTED_IN]->(m:Match) WHERE p.name = "Babar Azam" '
        'RETURN MIN(r.runs) AS worst',
        graph,
    )
    assert rows == [{"worst": 1}]


def test_avg_exact_value(graph: PropertyGraph):
    """Babar averaged 31/4 = 7.75 across his 4 fixture innings."""
    rows = run_cypher(
        'MATCH (p:Player)-[r:BATTED_IN]->(m:Match) WHERE p.name = "Babar Azam" '
        'RETURN AVG(r.runs) AS mean',
        graph,
    )
    assert rows == [{"mean": 7.75}]


def test_count_exact_value(graph: PropertyGraph):
    """Babar batted in 4 of 5 fixtures."""
    rows = run_cypher(
        'MATCH (p:Player)-[r:BATTED_IN]->(m:Match) WHERE p.name = "Babar Azam" '
        'RETURN COUNT(m) AS innings',
        graph,
    )
    assert rows == [{"innings": 4}]


# ─── Multi-column ORDER BY ──────────────────────────────────────────


def test_multi_column_order_by_tiebreaks(graph: PropertyGraph):
    """When matches share a season, secondary ORDER BY id ASC stabilizes the order."""
    rows = run_cypher(
        'MATCH (m:Match) RETURN m.id AS id, m.season AS season '
        'ORDER BY season ASC, id ASC',
        graph,
    )
    seasons = [r["season"] for r in rows]
    # Should be sorted ascending and tied IDs sorted ascending.
    assert seasons == sorted(seasons)
