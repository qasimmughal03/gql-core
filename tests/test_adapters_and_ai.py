"""Tests for zero-friction adapters and the natural language ask interface."""

from __future__ import annotations

import networkx as nx
import pytest

from gql_core.ai import (
    ask,
    clean_generated_gql,
    extract_schema_summary,
    format_schema_prompt,
    translate_to_gql,
)
from gql_core.graph import PropertyGraph
from gql_core.query.executor import run as run_query


class TestZeroFrictionAdapters:
    def test_from_edges_simple_pairs(self):
        edges = [("Alice", "Bob"), ("Bob", "Charlie")]
        graph = PropertyGraph.from_edges(edges)

        assert len(graph) == 3
        assert len(graph._edges) == 2
        assert "Alice" in graph._nodes
        assert "Bob" in graph._nodes
        assert "Charlie" in graph._nodes

        # Query directly with GQL-Core
        rows = run_query(
            'MATCH (a:Node)-[:CONNECTED_TO]->(b:Node) WHERE a.id = "Alice" RETURN b.id AS friend',
            graph,
        )
        assert rows == [{"friend": "Bob"}]

    def test_from_edges_with_labels_and_props(self):
        edges = [
            ("Alice", "Bob", "KNOWS", {"since": 2020}),
            ("Bob", "Charlie", "WORKS_WITH", {"dept": "Eng"}),
        ]
        graph = PropertyGraph.from_edges(edges)

        rows = run_query(
            "MATCH (a)-[r:KNOWS]->(b) RETURN a.id AS a_id, b.id AS b_id, r.since",
            graph,
        )
        assert rows == [{"a_id": "Alice", "b_id": "Bob", "since": 2020}]

    def test_from_records_dicts(self):
        nodes = [
            {"id": "p1", "label": "Person", "name": "Alice", "age": 30},
            {"id": "p2", "label": "Person", "name": "Bob", "age": 25},
        ]
        edges = [
            {"src": "p1", "dst": "p2", "label": "FRIENDS_WITH", "closeness": 5}
        ]
        graph = PropertyGraph.from_records(nodes, edges)

        assert len(graph) == 2
        assert len(graph._edges) == 1

        rows = run_query(
            "MATCH (a:Person)-[r:FRIENDS_WITH]->(b:Person) RETURN a.name AS a_name, b.name AS b_name, r.closeness",
            graph,
        )
        assert rows == [{"a_name": "Alice", "b_name": "Bob", "closeness": 5}]

    def test_from_networkx_graph(self):
        G = nx.DiGraph()
        G.add_node("alice", label="Person", role="Admin", clearance=5)
        G.add_node("server1", label="Server", ip="10.0.0.1")
        G.add_edge("alice", "server1", label="MANAGES", since=2022)

        graph = PropertyGraph.from_networkx(G)
        assert len(graph) == 2
        assert len(graph._edges) == 1

        rows = run_query(
            "MATCH (p:Person)-[m:MANAGES]->(s:Server) RETURN p.role, s.ip, m.since",
            graph,
        )
        assert rows == [{"role": "Admin", "ip": "10.0.0.1", "since": 2022}]

    def test_from_networkx_undirected_rpq(self):
        G = nx.path_graph(5)  # 0 - 1 - 2 - 3 - 4
        graph = PropertyGraph.from_networkx(G, default_node_label="Step", default_edge_label="NEXT")

        rows = run_query(
            "MATCH (a:Step)-[:NEXT*1..2]-(b:Step) WHERE a.id = 0 RETURN b.id ORDER BY b.id ASC",
            graph,
        )
        reachable = [r["id"] for r in rows]
        assert 1 in reachable
        assert 2 in reachable


class TestNaturalLanguageInterface:
    def test_clean_generated_gql(self):
        raw = "```gql\nMATCH (n:Person) RETURN n.name\n```"
        assert clean_generated_gql(raw) == "MATCH (n:Person) RETURN n.name"

        raw_cypher = "```cypher\nMATCH (m:Movie) WHERE m.year > 2000 RETURN m.title LIMIT 5\n```"
        assert clean_generated_gql(raw_cypher) == "MATCH (m:Movie) WHERE m.year > 2000 RETURN m.title LIMIT 5"

    def test_format_schema_prompt(self):
        G = nx.DiGraph()
        G.add_node("A", label="User", email="a@example.com")
        G.add_node("B", label="Post", title="Hello")
        G.add_edge("A", "B", label="AUTHORED", date="2026-01-01")

        graph = PropertyGraph.from_networkx(G)
        prompt = format_schema_prompt(graph)

        assert "(User)" in prompt
        assert "email" in prompt
        assert "[:AUTHORED]" in prompt

    def test_ask_with_mock_client(self):
        nodes = [
            {"id": "p1", "label": "Person", "name": "Alice"},
            {"id": "p2", "label": "Person", "name": "Bob"},
        ]
        edges = [{"src": "p1", "dst": "p2", "label": "KNOWS"}]
        graph = PropertyGraph.from_records(nodes, edges)

        # Mock LLM client that returns formal GQL
        def mock_llm(_prompt: str) -> str:
            return "MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN b.name AS friend"

        result = ask(graph, "Who does Alice know?", client=mock_llm, explain=True)
        assert result["query"] == "MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN b.name AS friend"
        assert result["count"] == 1
        assert result["results"] == [{"friend": "Bob"}]
