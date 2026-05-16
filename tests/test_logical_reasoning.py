"""Logical-Reasoning Benchmark correctness tests.

Each LR query is asserted against hand-computed expected results on the
fixture corpus, AND against cross-engine parity with the SQLite mirror.
Together these prove:

  (a) the underlying graph encoding is correct (Cypher matches expected),
  (b) the SQL mirror is faithful (SQL matches the same expected),
  (c) the two engines agree (no executor-vs-SQL semantic drift).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from benchmark.logical_reasoning import LR_QUERIES, expressibility
from benchmark.vs_sqlite import _canonical_rows, _resolve_start_id, _rows_equal
from graph.store import PropertyGraph
from ingestion.cricsheet_parser import CricsheetParser
from ingestion.validator import ShapeValidator
from query.executor import run as run_cypher
from scripts.build_sqlite_mirror import build_mirror

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


@pytest.fixture
def mirror(graph: PropertyGraph, tmp_path: Path) -> sqlite3.Connection:
    conn = build_mirror(graph, tmp_path / "lr.db")
    yield conn
    conn.close()


def _query_by_name(name: str) -> dict:
    return next(q for q in LR_QUERIES if q["name"] == name)


def _run_pair(graph, conn, raw_q):
    q = _resolve_start_id(raw_q, graph)
    cur = conn.cursor()
    cypher = run_cypher(q["cypher"], graph)
    sql = cur.execute(q["sql"]).fetchall()
    return q, cypher, sql


# ── LR1 — All-rounders (conjunctive multi-pattern) ──────────────────


def test_lr1_no_allrounder_in_fixtures(graph: PropertyGraph, mirror):
    """No fixture has the same player BOTH batting and bowling in one match."""
    q, cypher, sql = _run_pair(graph, mirror, _query_by_name("LR1_all_rounders"))
    assert cypher == []
    assert sql == []


# ── LR2 — Teammates within 2 hops (bounded RPQ on undirected edge) ──


def test_lr2_two_hop_teammates_of_babar_exact_set(graph: PropertyGraph, mirror):
    """Babar's 2-hop reach in the fixture graph = {Rizwan, Naseem, Shaheen, Shan}.

    Each PAK match contributes a clique. Across F1+F2+F3+F4+F5, Babar is in
    every PAK XI, so all PAK players who shared any match with anyone who
    shared a match with Babar are reachable within 2 hops. That equals
    every PAK player except Babar himself, which on the fixtures is exactly
    the 4 named players.
    """
    q, cypher, sql = _run_pair(graph, mirror, _query_by_name("LR2_teammates_within_two_hops"))
    names = sorted(r["within_2_hops"] for r in cypher)
    assert names == ["Mohammad Rizwan", "Naseem Shah", "Shaheen Afridi", "Shan Masood"]
    assert sorted(r[0] for r in sql) == names


def test_lr2_rpq_dedupes_targets(graph: PropertyGraph):
    """RPQ semantics: each reachable node appears once even if multiple paths exist.

    Without dedupe in `rpq_traverse`, Rizwan would appear as both a direct
    teammate AND as a 2-hop teammate via Shaheen, producing duplicate rows.
    """
    q = _resolve_start_id(_query_by_name("LR2_teammates_within_two_hops"), graph)
    rows = run_cypher(q["cypher"], graph)
    names = [r["within_2_hops"] for r in rows]
    assert len(names) == len(set(names)), f"duplicate names: {names}"


# ── LR3 — Test centurions (multi-edge constraint with threshold) ────


def test_lr3_no_century_in_fixtures(graph: PropertyGraph, mirror):
    """Fixtures cap batter scores at 11 runs, so no centurion exists."""
    q, cypher, sql = _run_pair(graph, mirror, _query_by_name("LR3_test_centurions"))
    assert cypher == []
    assert sql == []


def test_lr3_threshold_filter_excludes_below_100(graph: PropertyGraph):
    """Sanity: lowering threshold to >= 10 picks up Babar's fixture innings."""
    src = (
        'MATCH (p:Player)-[r:BATTED_IN]->(m:Match) '
        'WHERE r.runs >= 10 '
        'RETURN p.name AS player, COUNT(m) AS matches '
        'ORDER BY matches DESC, player ASC'
    )
    rows = run_cypher(src, graph)
    # Babar scored 11 in F1 and 10 in F4.
    assert rows[0] == {"player": "Babar Azam", "matches": 2}


# ── LR4 — Co-venue batters (heterogeneous-path composition) ─────────


def test_lr4_babar_co_venue_set(graph: PropertyGraph, mirror):
    """Players who batted at any venue where Babar batted, excluding Babar himself.

    Fixture-level enumeration:
      Karachi (F1): with Babar batting → Rizwan, Shaheen also batted there.
      Lahore (F2): with Babar batting → Shan, Cummins, Smith, Starc also batted there.
      unknown@unknown (F4): Babar is the only batter — no co-batters.
      Birmingham (F5 inn 1): with Babar batting → Joe Root batted in the super-over.
    Total expected co-venue batters: {Rizwan, Shaheen, Shan, Cummins, Smith, Starc, Joe Root} = 7.
    """
    q, cypher, sql = _run_pair(graph, mirror, _query_by_name("LR4_co_venue_batters"))
    expected_names = {
        "Mohammad Rizwan", "Shaheen Afridi", "Shan Masood",
        "Pat Cummins", "Steve Smith", "Mitchell Starc", "Joe Root",
    }
    assert {r["co_venue_batter"] for r in cypher} == expected_names
    assert {r[0] for r in sql} == expected_names
    # Each pair shares exactly one venue in the fixtures (each venue has 1 match).
    assert all(r["shared_venue_instances"] == 1 for r in cypher)
    assert all(r[1] == 1 for r in sql)


def test_lr4_inequality_operator_excludes_self(graph: PropertyGraph):
    """Babar Azam himself must not appear in the result (tests != operator)."""
    q = _resolve_start_id(_query_by_name("LR4_co_venue_batters"), graph)
    rows = run_cypher(q["cypher"], graph)
    assert "Babar Azam" not in {r["co_venue_batter"] for r in rows}


# ── LR5 — RPQ + numeric filter ──────────────────────────────────────


def test_lr5_terminates_and_cypher_sql_agree(graph: PropertyGraph, mirror):
    """The chosen start delivery may not have many followers in fixtures —
    the result is small (0 in most cases). What matters is: (a) the query
    terminates, (b) Cypher and SQL agree."""
    q, cypher, sql = _run_pair(graph, mirror, _query_by_name("LR5_scoring_chain_from_first_ball"))
    assert len(cypher) == 1
    assert len(sql) == 1
    assert cypher[0]["scoring_balls"] == sql[0][0]
    assert cypher[0]["scoring_balls"] >= 0


def test_lr5_known_chain_from_fixture_start(graph: PropertyGraph):
    """Hand-verified: from `1000001:1:0.1`, balls within 12 hops with runs_batter > 0
    are deliveries 0.2 (six), 0.3 (one), 0.6 (two from Shaheen). → 3 scoring balls.
    """
    src = (
        'MATCH (d1:Delivery)-[:NEXT_DELIVERY*1..12]->(d2:Delivery) '
        'WHERE d1.id = "1000001:1:0.1" AND d2.runs_batter > 0 '
        'RETURN COUNT(d2) AS scoring_balls'
    )
    rows = run_cypher(src, graph)
    assert rows == [{"scoring_balls": 3}]


# ── Cross-engine parity (always required) ───────────────────────────


def test_all_lr_queries_cross_engine_parity(graph: PropertyGraph, mirror):
    for raw_q in LR_QUERIES:
        q, cypher, sql = _run_pair(graph, mirror, raw_q)
        canon_c = _canonical_rows(cypher, q["key_columns"])
        canon_s = _canonical_rows(sql, q["key_columns"])
        assert _rows_equal(canon_c, canon_s), (q["name"], canon_c, canon_s)


# ── Expressibility metric sanity ────────────────────────────────────


def test_lr2_requires_recursive_sql():
    """Bounded transitive closure forces a WITH RECURSIVE in SQL."""
    e = expressibility(_query_by_name("LR2_teammates_within_two_hops"))
    assert e["sql_recursive"] is True
    assert e["reasoning_pattern"] == "bounded transitive closure (RPQ)"


def test_lr5_requires_recursive_sql():
    e = expressibility(_query_by_name("LR5_scoring_chain_from_first_ball"))
    assert e["sql_recursive"] is True


def test_all_lr_sql_at_least_as_long_as_cypher():
    for q in LR_QUERIES:
        e = expressibility(q)
        assert e["sql_tokens"] >= e["cypher_tokens"], q["name"]
