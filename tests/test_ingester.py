"""Tests for the generic GraphIngester (gql-graph-json format)."""

from __future__ import annotations

from pathlib import Path

import pytest

from gql_core.graph import PropertyGraph
from gql_core.ingester import GraphIngester, IngestReport
from gql_core.validator import ShapeValidator

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "generic"
SHAPES = FIXTURES / "shapes.yaml"
GRAPH_JSON = FIXTURES / "social_graph.json"


@pytest.fixture
def validator():
    return ShapeValidator(SHAPES)


@pytest.fixture
def graph():
    return PropertyGraph()


@pytest.fixture
def ingester(graph, validator):
    return GraphIngester(graph, validator)


class TestGraphIngester:
    def test_ingest_file_counts(self, graph, ingester):
        n, e = ingester.ingest_file(GRAPH_JSON)
        assert n == 6  # 4 Person + 2 City
        assert e == 8  # 4 KNOWS + 4 LIVES_IN
        stats = graph.stats()
        assert stats["nodes"] == 6
        assert stats["edges"] == 8

    def test_ingest_file_labels(self, graph, ingester):
        ingester.ingest_file(GRAPH_JSON)
        by_label = graph.stats()["by_label"]
        assert by_label["Person"] == 4
        assert by_label["City"] == 2
        edges_by_label = graph.stats()["edges_by_label"]
        assert edges_by_label["KNOWS"] == 4
        assert edges_by_label["LIVES_IN"] == 4

    def test_idempotent_reingest(self, graph, ingester):
        ingester.ingest_file(GRAPH_JSON)
        n2, e2 = ingester.ingest_file(GRAPH_JSON)
        # Second ingest should add zero new nodes/edges (same IDs).
        assert n2 == 0
        assert e2 == 0
        assert graph.stats()["nodes"] == 6
        assert graph.stats()["edges"] == 8

    def test_ingest_directory(self, graph, ingester):
        report = ingester.ingest_directory(FIXTURES)
        assert report.files >= 1
        assert report.nodes >= 6
        assert report.edges >= 8

    def test_missing_id_raises(self, graph, ingester):
        data = {"nodes": [{"@type": "Person", "name": "NoID"}]}
        with pytest.raises(KeyError, match="missing @id"):
            ingester.ingest_data(data)

    def test_missing_type_raises(self, graph, ingester):
        data = {"nodes": [{"@id": "x", "name": "NoType"}]}
        with pytest.raises(KeyError, match="missing @type"):
            ingester.ingest_data(data)

    def test_edge_missing_src_raises(self, graph, ingester):
        data = {
            "nodes": [{"@id": "a", "@type": "Person", "name": "A"}],
            "edges": [{"@type": "KNOWS", "@dst": "a"}],
        }
        with pytest.raises(KeyError, match="missing @src"):
            ingester.ingest_data(data)

    def test_edge_unknown_endpoint_raises(self, graph, ingester):
        data = {
            "edges": [
                {"@type": "KNOWS", "@src": "ghost", "@dst": "also_ghost"}
            ]
        }
        with pytest.raises(KeyError, match="not found"):
            ingester.ingest_data(data)

    def test_auto_edge_id(self, graph, ingester):
        data = {
            "nodes": [
                {"@id": "a", "@type": "Person", "name": "A"},
                {"@id": "b", "@type": "Person", "name": "B"},
            ],
            "edges": [
                {"@type": "KNOWS", "@src": "a", "@dst": "b", "since": 2023}
            ],
        }
        ingester.ingest_data(data)
        edges = list(graph.edges_by_label("KNOWS"))
        assert len(edges) == 1
        # Auto-generated ID: {label}:{src}:{dst}
        assert edges[0].id == "KNOWS:a:b"

    def test_validation_catches_bad_type(self, graph, ingester):
        data = {
            "nodes": [
                {"@id": "a", "@type": "Person", "name": "A", "age": "not_a_number"}
            ]
        }
        with pytest.raises(Exception):  # ShapeViolationError
            ingester.ingest_data(data)

    def test_ingest_report_as_dict(self):
        report = IngestReport(files=2, nodes=10, edges=20)
        d = report.as_dict()
        assert d["files"] == 2
        assert d["nodes"] == 10
        assert d["edges"] == 20
        assert d["errors"] == []
