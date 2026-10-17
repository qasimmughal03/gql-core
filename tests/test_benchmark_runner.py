"""Tests for the generic benchmark runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from gql_core.benchmark import (
    SuiteLoadError,
    canonical_rows,
    load_suite,
    rows_equal,
    run_benchmark,
)
from gql_core.graph import PropertyGraph
from gql_core.ingester import GraphIngester
from gql_core.validator import ShapeValidator

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "generic"
SHAPES = FIXTURES / "shapes.yaml"
GRAPH_JSON = FIXTURES / "social_graph.json"
SUITE = FIXTURES / "suite.yaml"


@pytest.fixture
def graph():
    g = PropertyGraph()
    validator = ShapeValidator(SHAPES)
    ingester = GraphIngester(g, validator)
    ingester.ingest_file(GRAPH_JSON)
    return g


class TestCanonicalRows:
    def test_dict_rows(self):
        rows = [{"name": "Bob", "age": 25}, {"name": "Alice", "age": 30}]
        canon = canonical_rows(rows, ("name", "age"))
        assert canon == [("Alice", 30), ("Bob", 25)]

    def test_tuple_rows(self):
        rows = [("Bob", 25), ("Alice", 30)]
        canon = canonical_rows(rows)
        assert canon == [("Alice", 30), ("Bob", 25)]

    def test_none_ordering(self):
        rows = [{"name": "Bob", "age": None}, {"name": "Alice", "age": 30}]
        canon = canonical_rows(rows, ("name", "age"))
        assert canon == [("Alice", 30), ("Bob", None)]

    def test_rows_equal_float_tolerance(self):
        a = [(1.0, 2.0)]
        b = [(1.0000001, 2.0)]
        assert rows_equal(a, b)

    def test_rows_equal_mismatch(self):
        a = [(1, 2)]
        b = [(1, 3)]
        assert not rows_equal(a, b)


class TestLoadSuite:
    def test_load_valid_suite(self):
        data = load_suite(SUITE)
        assert data["name"] == "social-graph-benchmark"
        assert len(data["queries"]) == 6

    def test_missing_name_raises(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("queries: []")
        with pytest.raises(SuiteLoadError, match="missing required key"):
            load_suite(f)

    def test_empty_queries_raises(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("name: test\nqueries: []")
        with pytest.raises(SuiteLoadError, match="non-empty"):
            load_suite(f)

    def test_missing_gql_raises(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("name: test\nqueries:\n  - name: q1\n")
        with pytest.raises(SuiteLoadError, match="missing 'gql'"):
            load_suite(f)


class TestRunBenchmark:
    def test_all_queries_pass(self, graph):
        report = run_benchmark(
            graph, SUITE, shapes_path=SHAPES, iters=5
        )
        assert report["meta"]["suite"] == "social-graph-benchmark"
        results = report["results"]
        assert len(results) == 6
        for r in results:
            assert r["status"] == "pass", f"{r['name']} failed: {r}"

    def test_with_sql_mirror(self, graph, tmp_path):
        db_path = tmp_path / "test.db"
        report = run_benchmark(
            graph, SUITE, shapes_path=SHAPES, db_path=db_path, iters=5
        )
        results = report["results"]
        # Q1 (count_people) has SQL — should have sql timing.
        assert results[0].get("correct_sql") is True
        assert results[0].get("sql") is not None

    def test_expected_mismatch_detected(self, graph, tmp_path):
        # Write a suite with deliberately wrong expected.
        suite_path = tmp_path / "bad_suite.yaml"
        suite_path.write_text(
            """name: bad
queries:
  - name: fail_query
    gql: "MATCH (p:Person) RETURN COUNT(p) AS count"
    key_columns: [count]
    expected:
      - [999]
"""
        )
        report = run_benchmark(graph, suite_path, iters=3)
        assert report["results"][0]["status"] == "fail"
        assert report["results"][0]["correct_expected"] is False
