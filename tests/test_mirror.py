"""Tests for the generic SQLite mirror builder."""

from __future__ import annotations

from pathlib import Path

import pytest

from gql_core.graph import PropertyGraph
from gql_core.ingester import GraphIngester
from gql_core.mirror import build_mirror
from gql_core.validator import ShapeValidator

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "generic"
SHAPES = FIXTURES / "shapes.yaml"
GRAPH_JSON = FIXTURES / "social_graph.json"


@pytest.fixture
def graph():
    g = PropertyGraph()
    validator = ShapeValidator(SHAPES)
    ingester = GraphIngester(g, validator)
    ingester.ingest_file(GRAPH_JSON)
    return g


class TestMirror:
    def test_build_mirror_table_counts(self, graph, tmp_path):
        db_path = tmp_path / "test.db"
        conn = build_mirror(graph, SHAPES, db_path)
        cur = conn.cursor()

        tables = {
            row[0]
            for row in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "person" in tables
        assert "city" in tables
        assert "knows" in tables
        assert "lives_in" in tables

        assert cur.execute("SELECT COUNT(*) FROM person").fetchone()[0] == 4
        assert cur.execute("SELECT COUNT(*) FROM city").fetchone()[0] == 2
        assert cur.execute("SELECT COUNT(*) FROM knows").fetchone()[0] == 4
        assert cur.execute("SELECT COUNT(*) FROM lives_in").fetchone()[0] == 4
        conn.close()

    def test_mirror_overwrites_existing(self, graph, tmp_path):
        db_path = tmp_path / "test.db"
        db_path.write_text("garbage")
        conn = build_mirror(graph, SHAPES, db_path)
        cur = conn.cursor()
        assert cur.execute("SELECT COUNT(*) FROM person").fetchone()[0] == 4
        conn.close()

    def test_mirror_indexes_exist(self, graph, tmp_path):
        db_path = tmp_path / "test.db"
        conn = build_mirror(graph, SHAPES, db_path)
        cur = conn.cursor()
        indexes = {
            row[1]
            for row in cur.execute(
                "SELECT * FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        # Every edge table gets src_id + dst_id indexes.
        assert any("knows" in idx and "src_id" in idx for idx in indexes)
        assert any("knows" in idx and "dst_id" in idx for idx in indexes)
        assert any("lives_in" in idx and "src_id" in idx for idx in indexes)
        assert any("lives_in" in idx and "dst_id" in idx for idx in indexes)
        conn.close()

    def test_column_types(self, graph, tmp_path):
        db_path = tmp_path / "test.db"
        conn = build_mirror(graph, SHAPES, db_path)
        cur = conn.cursor()
        info = cur.execute("PRAGMA table_info(person)").fetchall()
        # (cid, name, type, notnull, dflt_value, pk)
        col_types = {row[1]: row[2] for row in info}
        assert col_types["id"] == "TEXT"
        assert col_types["name"] == "TEXT"
        assert col_types["age"] == "INTEGER"
        assert col_types["city"] == "TEXT"
        conn.close()
