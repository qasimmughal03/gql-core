"""CI Smoke Tests for Benchmark Adapters (TCK and LDBC SNB).

Verifies that the openCypher TCK adapter and LDBC SNB execution flow run
cleanly against public APIs and finish in well under 5 seconds.
"""

from __future__ import annotations

import pytest
import gql_core
from gql_core import PropertyGraph, Node, Edge
from benchmark.tck.gherkin_parser import TCKScenario
from benchmark.tck.tck_adapter import run_scenario


def test_tck_adapter_smoke():
    """Verify openCypher TCK scenario parser, loader, and executor run cleanly."""
    scenario = TCKScenario(
        feature="SmokeFeature - Basic Graph Query",
        scenario_id="Smoke#1",
        name="Matching single node",
        file_path="smoke.feature",
        background_create=["CREATE (:Person {name: 'Alice', age: 30})"],
        scenario_create=["CREATE (:Person {name: 'Bob', age: 25})"],
        query="MATCH (n:Person) WHERE n.age > 26 RETURN n.name AS name",
        expected_kind="rows",
        expected_columns=["name"],
        expected_rows=[{"name": "Alice"}],
        in_order=False,
    )

    result = run_scenario(scenario)
    assert result["status"] == "passed", f"TCK smoke scenario failed: {result.get('reason')}"
    assert "Exact match" in result["reason"]


def test_snb_smoke_workflow():
    """Verify LDBC SNB queries execute correctly over an in-memory PropertyGraph."""
    graph = PropertyGraph()

    # Nodes
    graph.add_node(Node(id="p1", label="Person", props={"id": 1001, "firstName": "Alice", "lastName": "Smith", "creationDate": 1000}))
    graph.add_node(Node(id="p2", label="Person", props={"id": 1002, "firstName": "Bob", "lastName": "Jones", "creationDate": 2000}))
    graph.add_node(Node(id="c1", label="City", props={"id": 501, "name": "London"}))
    graph.add_node(Node(id="post1", label="Post", props={"id": 9001, "content": "Hello World", "creationDate": 1500}))

    # Edges
    graph.add_edge(Edge(id="e1", label="IS_LOCATED_IN", src="p1", dst="c1", props={}))
    graph.add_edge(Edge(id="e2", label="KNOWS", src="p1", dst="p2", props={"creationDate": 1200}))
    graph.add_edge(Edge(id="e3", label="HAS_CREATOR", src="post1", dst="p2", props={}))

    # 1. Test IS1 query
    is1_q = (
        "MATCH (n:Person {id: 1001})-[:IS_LOCATED_IN]->(p:City) "
        "RETURN n.firstName AS firstName, p.id AS cityId"
    )
    rows_is1 = gql_core.run(is1_q, graph)
    assert len(rows_is1) == 1
    assert rows_is1[0] == {"firstName": "Alice", "cityId": 501}

    # 2. Test IS3 query (undirected KNOWS)
    is3_q = (
        "MATCH (n:Person {id: 1002})-[r:KNOWS]-(friend:Person) "
        "RETURN friend.id AS personId, r.creationDate AS friendshipCreationDate"
    )
    rows_is3 = gql_core.run(is3_q, graph)
    assert len(rows_is3) == 1
    assert rows_is3[0] == {"personId": 1001, "friendshipCreationDate": 1200}

    # 3. Test IC2 query (2-hop join with filter)
    ic2_q = (
        "MATCH (:Person {id: 1001})-[:KNOWS]-(friend:Person)<-[:HAS_CREATOR]-(message:Post) "
        "WHERE message.creationDate <= 2000 "
        "RETURN friend.id AS personId, message.content AS postContent "
        "ORDER BY message.creationDate DESC "
        "LIMIT 10"
    )
    rows_ic2 = gql_core.run(ic2_q, graph)
    assert len(rows_ic2) == 1
    assert rows_ic2[0] == {"personId": 1002, "postContent": "Hello World"}
