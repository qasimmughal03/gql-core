"""Benchmark harness sanity tests on fixture data."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from benchmark.queries import QUERIES, expressibility
from benchmark.logical_reasoning import LR_QUERIES
from benchmark.vs_sqlite import (
    _canonical_rows,
    _resolve_start_id,
    _rows_equal,
    benchmark,
)
from graph.store import PropertyGraph
from ingestion.cricsheet_parser import CricsheetParser
from ingestion.validator import ShapeValidator
from query.executor import run as run_cypher
from scripts.build_sqlite_mirror import (
    EDGE_LABEL_TO_TABLE,
    NODE_LABEL_TO_TABLE,
    build_mirror,
)

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
    db_path = tmp_path / "cricket.db"
    conn = build_mirror(graph, db_path)
    yield conn
    conn.close()


def test_sqlite_mirror_row_counts_match_graph(graph: PropertyGraph, mirror: sqlite3.Connection):
    cur = mirror.cursor()
    stats = graph.stats()
    for label, table in NODE_LABEL_TO_TABLE.items():
        sql_count = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        graph_count = stats["by_label"].get(label, 0)
        assert sql_count == graph_count, (label, table, sql_count, graph_count)
    for label, table in EDGE_LABEL_TO_TABLE.items():
        sql_count = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        graph_count = stats["edges_by_label"].get(label, 0)
        assert sql_count == graph_count, (label, table, sql_count, graph_count)


def test_q1_q5_results_match_between_engines(graph: PropertyGraph, mirror: sqlite3.Connection):
    cur = mirror.cursor()
    for raw_q in QUERIES + LR_QUERIES:
        q = _resolve_start_id(raw_q, graph)
        cypher_rows = run_cypher(q["cypher"], graph)
        sql_rows = cur.execute(q["sql"]).fetchall()
        is_distinct = "DISTINCT" in q.get("sql", "").upper()
        canon_cypher = _canonical_rows(cypher_rows, q["key_columns"], distinct=is_distinct)
        canon_sql = _canonical_rows(sql_rows, q["key_columns"])
        assert _rows_equal(canon_cypher, canon_sql), (
            q["name"],
            "\ncypher:",
            canon_cypher,
            "\nsql:",
            canon_sql,
        )


def test_benchmark_writes_results_json_with_required_keys(
    graph: PropertyGraph, tmp_path: Path
):
    from benchmark.logical_reasoning import LR_QUERIES

    db_path = tmp_path / "cricket.db"
    build_mirror(graph, db_path).close()
    out = benchmark(graph, db_path, iters=2)
    assert "meta" in out
    assert "direct_queries" in out and "logical_reasoning" in out
    assert out["meta"]["iters"] == 2
    assert "methodology" in out["meta"]
    assert "environment" in out["meta"]
    assert {t["name"] for t in out["meta"]["methodology"]["tracks"]} >= {
        "fixture_gold_oracle",
        "full_corpus_sql_parity",
        "expressibility",
        "nl_to_gql_model_accuracy",
    }
    assert len(out["direct_queries"]) == len(QUERIES)
    assert len(out["logical_reasoning"]) == len(LR_QUERIES)
    for q in out["direct_queries"] + out["logical_reasoning"]:
        for key in ("name", "cypher", "sql", "expressibility", "result_correct"):
            assert key in q
        assert "median_ms" in q["cypher"]
        assert "median_ms" in q["cypher_parse_plan"]
        assert "median_ms" in q["cypher_execute"]
        assert "median_ms" in q["sql"]
        assert q["result_correct"] is True


def test_expressibility_sql_tokens_at_least_match_cypher():
    # Thesis claim: structured graph queries are at most as long as their
    # SQL equivalents (and usually shorter). Q5 also requires WITH RECURSIVE.
    for q in QUERIES:
        e = expressibility(q)
        assert e["sql_tokens"] >= e["cypher_tokens"], q["name"]
    q5 = next(q for q in QUERIES if q["name"].startswith("Q5"))
    assert expressibility(q5)["sql_recursive"] is True


def test_canonical_rows_sorts_stably():
    rows = [{"x": 2, "y": "b"}, {"x": 1, "y": "a"}, {"x": 1, "y": "b"}]
    assert _canonical_rows(rows, ("x", "y")) == [(1, "a"), (1, "b"), (2, "b")]


def test_rows_equal_handles_floats():
    assert _rows_equal([(1.0,)], [(1.0 + 1e-9,)]) is True
    assert _rows_equal([(1.0,)], [(1.5,)]) is False


def test_build_mirror_overwrites_existing_db(graph: PropertyGraph, tmp_path: Path):
    db_path = tmp_path / "cricket.db"
    build_mirror(graph, db_path).close()
    # Re-build should not fail and should produce a valid DB.
    conn = build_mirror(graph, db_path)
    cur = conn.cursor()
    n = cur.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    conn.close()
    assert n == 5


def test_sqlite_mirror_has_benchmark_indexes(graph: PropertyGraph, mirror: sqlite3.Connection):
    cur = mirror.cursor()
    index_names = set()
    for table in ("players", "matches", "venues", "deliveries", "batted_in"):
        index_names |= {row[1] for row in cur.execute(f"PRAGMA index_list({table})")}
    assert "idx_players_name" in index_names
    assert "idx_matches_format" in index_names
    assert "idx_venues_city" in index_names
    assert "idx_deliveries_runs_batter" in index_names
    assert "idx_batted_in_match_player" in index_names
