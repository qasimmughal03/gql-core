"""Executor + planner tests against the fixture corpus."""

from __future__ import annotations

from pathlib import Path

import pytest

from graph.store import PropertyGraph
from ingestion.cricsheet_parser import CricsheetParser
from ingestion.validator import ShapeValidator
from query.executor import run
from query.parser import parse
from query.planner import ScanOp, plan as plan_query
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


# ── Q1 — top run scorers ────────────────────────────────────────────


def test_q1_returns_top_run_scorers(graph: PropertyGraph):
    rows = run(
        """MATCH (p:Player)-[r:BATTED_IN]->(m:Match)
           RETURN p.name AS player, SUM(r.runs) AS career_runs
           ORDER BY career_runs DESC LIMIT 3""",
        graph,
    )
    assert rows[0] == {"player": "Babar Azam", "career_runs": 31}
    assert rows[1] == {"player": "Shaheen Afridi", "career_runs": 2}
    assert rows[2] == {"player": "Joe Root", "career_runs": 1}


# ── Q2 — best bowling at venue ──────────────────────────────────────


def test_q2_filters_by_venue_city(graph: PropertyGraph):
    rows = run(
        """MATCH (p:Player)-[r:BOWLED_IN]->(m:Match)-[:PLAYED_AT]->(v:Venue)
           WHERE v.city = "Karachi"
           RETURN p.name AS bowler, MAX(r.wickets) AS best_haul
           ORDER BY best_haul DESC LIMIT 5""",
        graph,
    )
    assert rows == [{"bowler": "Jofra Archer", "best_haul": 1}]


def test_q2_no_results_for_unknown_city(graph: PropertyGraph):
    rows = run(
        """MATCH (p:Player)-[r:BOWLED_IN]->(m:Match)-[:PLAYED_AT]->(v:Venue)
           WHERE v.city = "Atlantis"
           RETURN p.name, MAX(r.wickets)""",
        graph,
    )
    # Aggregate over empty set: one group with COUNT/SUM=0 etc., but here
    # group_keys is non-empty → groups stays empty → empty result.
    assert rows == []


# ── Q3 — captain win counts ─────────────────────────────────────────


def test_q3_captain_count_for_pakistan_wins(graph: PropertyGraph):
    rows = run(
        """MATCH (p:Player)-[:CAPTAINED]->(m:Match)
           WHERE m.outcome_winner = "Pakistan" AND p.country = "PAK"
           RETURN p.name AS captain, COUNT(m) AS wins
           ORDER BY wins DESC LIMIT 5""",
        graph,
    )
    assert rows == [{"captain": "Babar Azam", "wins": 4}]


# ── Q4 — TEAMMATES_WITH undirected ──────────────────────────────────


def test_q4_teammates_undirected(graph: PropertyGraph):
    rows = run(
        """MATCH (p1:Player)-[t:TEAMMATES_WITH]-(p2:Player)
           WHERE p1.name = "Babar Azam"
           RETURN p2.name AS partner, t.match_count AS shared
           ORDER BY shared DESC LIMIT 10""",
        graph,
    )
    counts = {r["partner"]: r["shared"] for r in rows}
    assert counts["Mohammad Rizwan"] == 4
    assert counts["Shaheen Afridi"] == 3
    assert counts["Shan Masood"] == 1
    assert counts["Naseem Shah"] == 1


def test_q4_undirected_symmetry(graph: PropertyGraph):
    """Querying with p2.name=X yields the same partner set as p1.name=X."""
    rows_a = run(
        """MATCH (p1:Player)-[t:TEAMMATES_WITH]-(p2:Player)
           WHERE p1.name = "Babar Azam"
           RETURN p2.name AS partner""",
        graph,
    )
    rows_b = run(
        """MATCH (p1:Player)-[t:TEAMMATES_WITH]-(p2:Player)
           WHERE p2.name = "Babar Azam"
           RETURN p1.name AS partner""",
        graph,
    )
    assert {r["partner"] for r in rows_a} == {r["partner"] for r in rows_b}


# ── Q5 — Kleene star over NEXT_DELIVERY ─────────────────────────────


def test_q5_kleene_star_bounded_terminates(graph: PropertyGraph):
    rows = run(
        """MATCH (d:Delivery)-[:NEXT_DELIVERY*1..3]->(d2:Delivery)
           WHERE d.id = "1000001:1:0.1"
           RETURN d.id AS start, COUNT(d2) AS reachable""",
        graph,
    )
    assert rows == [{"start": "1000001:1:0.1", "reachable": 3}]


def test_q5_kleene_unbounded_visits_all_chained(graph: PropertyGraph):
    rows = run(
        """MATCH (d:Delivery)-[:NEXT_DELIVERY*]->(d2:Delivery)
           WHERE d.id = "1000001:1:0.1"
           RETURN COUNT(d2) AS reachable""",
        graph,
    )
    # First innings of fixture 1000001 has 7 deliveries → 6 reachable from 0.1.
    assert rows[0]["reachable"] == 6


# ── Aggregation ────────────────────────────────────────────────────


def test_count_sum_avg_min_max_each_executes(graph: PropertyGraph):
    for agg, expected_min in (
        ("COUNT", 1),
        ("SUM", 0),
        ("MIN", 0),
        ("MAX", 0),
        ("AVG", 0),
    ):
        rows = run(
            f"""MATCH (p:Player)-[r:BATTED_IN]->(m:Match)
                RETURN {agg}(r.runs) AS v""",
            graph,
        )
        assert rows[0]["v"] is not None or agg == "AVG"
        if agg == "COUNT":
            assert rows[0]["v"] >= expected_min


# ── Predicate pushdown ─────────────────────────────────────────────


def test_predicate_pushed_into_scan_for_single_var():
    src = """MATCH (p:Player)-[r:BOWLED_IN]->(m:Match)-[:PLAYED_AT]->(v:Venue)
             WHERE v.city = "Karachi"
             RETURN p.name"""
    p = plan_query(parse(src))
    # Find the ScanOp / ExpandOp for v and assert v.city push-down landed there.
    from query.planner import ExpandOp
    found = False
    for op in p.ops:
        if isinstance(op, ExpandOp) and op.to_var == "v":
            for cmp in op.pushed:
                if cmp.lhs.var == "v" and cmp.lhs.prop == "city":
                    found = True
    assert found, "v.city predicate was not pushed into the v Expand"


# ── Edge cases ─────────────────────────────────────────────────────


def test_unknown_label_returns_empty(graph: PropertyGraph):
    rows = run("MATCH (x:Phantom) RETURN x.id", graph)
    assert rows == []


def test_order_by_and_limit_after_aggregation(graph: PropertyGraph):
    rows = run(
        """MATCH (p:Player)-[r:BATTED_IN]->(m:Match)
           RETURN p.name AS player, SUM(r.runs) AS runs
           ORDER BY runs DESC LIMIT 2""",
        graph,
    )
    assert len(rows) == 2
    assert rows[0]["runs"] >= rows[1]["runs"]


def test_multi_pattern_join(graph: PropertyGraph):
    rows = run(
        """MATCH (p:Player)-[:BATTED_IN]->(m:Match),
                 (p)-[:CAPTAINED]->(m)
           RETURN p.name AS player, m.id AS match_id""",
        graph,
    )
    # Babar captained and batted in F1, F2, F3, F4, F5 — but he didn't bat in F3
    # (only Kohli batted). So the join yields {F1, F2, F4, F5} for Babar.
    babar_matches = {r["match_id"] for r in rows if r["player"] == "Babar Azam"}
    assert babar_matches == {"1000001", "1000002", "1000004", "1000005"}


def test_filter_with_or(graph: PropertyGraph):
    rows = run(
        """MATCH (p:Player)
           WHERE p.country = "PAK" OR p.country = "ENG"
           RETURN p.name AS name""",
        graph,
    )
    countries = {r["name"] for r in rows}
    assert "Babar Azam" in countries
    assert "Joe Root" in countries
    assert "Virat Kohli" not in countries


# ── Semantic validation ────────────────────────────────────────────


def test_semantic_rejects_unbound_projection_variable(graph: PropertyGraph):
    with pytest.raises(SemanticError, match="unbound variable"):
        run(
            "MATCH (p:Player)-[:BATTED_IN]->(m:Match) "
            "RETURN b.runs AS runs",
            graph,
        )


def test_semantic_rejects_unknown_property_on_known_label(graph: PropertyGraph):
    with pytest.raises(SemanticError, match="unknown node property"):
        run("MATCH (p:Player) RETURN p.wickets AS wickets", graph)


def test_semantic_rejects_unknown_edge_label(graph: PropertyGraph):
    with pytest.raises(SemanticError, match="Unknown edge label"):
        run(
            'MATCH (m:Match)-[:OUTCOME_WINNER]->(w:Match) '
            'WHERE w.outcome_winner = "Pakistan" RETURN COUNT(m) AS n',
            graph,
        )


def test_semantic_rejects_impossible_directed_endpoint_order(graph: PropertyGraph):
    with pytest.raises(SemanticError, match="expects endpoints Match -> Venue"):
        run(
            "MATCH (v:Venue)-[:PLAYED_AT]->(m:Match) "
            "RETURN COUNT(m) AS n",
            graph,
        )
