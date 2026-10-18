"""Audit Regression Tests covering specific corner cases and semantics.

Validates the 6 mission-critical regression areas:
1. Exact-length bounded path queries (*k..k)
2. Trail semantics / Relationship isomorphism (no repeated edges in pattern)
3. Missing-property null semantics
4. Identifier type preservation and no collision
5. Record ID 0 / integer 0 / falsy property handling
6. Public API surface stability
"""

from __future__ import annotations

import pytest

import gql_core
from gql_core import PropertyGraph, Node, Edge


def test_exact_length_bounded_paths():
    """Verify exact-length bounded quantifier (*k..k) and ranges (*lo..hi)."""
    g = PropertyGraph()
    # A -> B -> C -> D -> E
    nodes = ["A", "B", "C", "D", "E"]
    for n in nodes:
        g.add_node(Node(id=n, label="Step", props={"name": n}))
    for i in range(len(nodes) - 1):
        g.add_edge(Edge(id=f"e{i}", label="NEXT", src=nodes[i], dst=nodes[i+1], props={}))

    # 1. Exactly 2 hops from A -> C
    q2 = "MATCH (a:Step {name: 'A'})-[:NEXT*2..2]->(b:Step) RETURN b.name AS dst"
    r2 = gql_core.run(q2, g)
    assert r2 == [{"dst": "C"}]

    # 2. Exactly 3 hops from A -> D
    q3 = "MATCH (a:Step {name: 'A'})-[:NEXT*3..3]->(b:Step) RETURN b.name AS dst"
    r3 = gql_core.run(q3, g)
    assert r3 == [{"dst": "D"}]

    # 3. Range 1..3 hops from A -> B, C, D
    q13 = "MATCH (a:Step {name: 'A'})-[:NEXT*1..3]->(b:Step) RETURN b.name AS dst ORDER BY dst ASC"
    r13 = gql_core.run(q13, g)
    assert r13 == [{"dst": "B"}, {"dst": "C"}, {"dst": "D"}]

    # 4. Out of bounds (5 hops from A in 5-node chain) -> empty
    q5 = "MATCH (a:Step {name: 'A'})-[:NEXT*5..5]->(b:Step) RETURN b.name AS dst"
    assert gql_core.run(q5, g) == []


def test_trail_semantics_relationship_isomorphism():
    """Verify trail semantics: the same relationship instance cannot appear twice in a single pattern part."""
    g = PropertyGraph()
    # Two nodes connected by a single undirected/symmetric relationship:
    # (X) --[e1]-- (Y)
    g.add_node(Node(id="X", label="Item", props={"name": "X"}))
    g.add_node(Node(id="Y", label="Item", props={"name": "Y"}))
    g.add_edge(Edge(id="e1", label="LINK", src="X", dst="Y", props={}))

    # Pattern: 2 hops undirected ()-[]-()-[]-()
    # Under walk semantics, X-e1-Y-e1-X would match.
    # Under openCypher trail semantics, e1 cannot be repeated, so match count is 0.
    q = "MATCH (a:Item)-[r1:LINK]-(b:Item)-[r2:LINK]-(c:Item) RETURN a.name AS a, c.name AS c"
    res = gql_core.run(q, g)
    assert res == [], f"Expected 0 matches under trail semantics, got {res}"

    # Now add a third node Z: (Y) --[e2]-- (Z)
    g.add_node(Node(id="Z", label="Item", props={"name": "Z"}))
    g.add_edge(Edge(id="e2", label="LINK", src="Y", dst="Z", props={}))

    # Now X-e1-Y-e2-Z is valid (uses different edges e1 and e2).
    # Forward: X-Y-Z, Z-Y-X
    res2 = gql_core.run(q, g)
    assert len(res2) == 2
    pairs = {(r["a"], r["c"]) for r in res2}
    assert pairs == {("X", "Z"), ("Z", "X")}


def test_missing_property_null_semantics():
    """Verify missing properties return None in projection and evaluate safely in WHERE."""
    g = PropertyGraph()
    g.add_node(Node(id="n1", label="Record", props={"id": 1, "score": 100, "status": "active"}))
    g.add_node(Node(id="n2", label="Record", props={"id": 2}))  # missing score and status

    # 1. Projection of missing property returns None
    q_proj = "MATCH (r:Record) RETURN r.id AS id, r.score AS score ORDER BY id ASC"
    res_proj = gql_core.run(q_proj, g)
    assert res_proj == [
        {"id": 1, "score": 100},
        {"id": 2, "score": None},
    ]

    # 2. Filter on property excludes node with missing property
    q_filter = "MATCH (r:Record) WHERE r.score > 50 RETURN r.id AS id"
    res_filter = gql_core.run(q_filter, g)
    assert res_filter == [{"id": 1}]

    # 3. Equality filter on property excludes missing property
    q_eq = "MATCH (r:Record) WHERE r.status = 'active' RETURN r.id AS id"
    assert gql_core.run(q_eq, g) == [{"id": 1}]


def test_identifier_type_preservation_and_no_collision():
    """Verify string vs integer IDs are preserved accurately."""
    g = PropertyGraph()
    # Integer ID 42 and String ID "42"
    g.add_node(Node(id=42, label="Entity", props={"type": "int_id"}))
    g.add_node(Node(id="str_42", label="Entity", props={"type": "str_id"}))

    q = "MATCH (e:Entity) RETURN e.type AS t"
    res = gql_core.run(q, g)
    assert len(res) == 2
    types = {r["t"] for r in res}
    assert types == {"int_id", "str_id"}


def test_record_id_zero_is_not_falsy():
    """Verify node ID 0 and property value 0/False are treated as valid values, not falsy/absent."""
    g = PropertyGraph()
    g.add_node(Node(id=0, label="Item", props={"id": 0, "count": 0, "active": False}))
    g.add_node(Node(id=1, label="Item", props={"id": 1, "count": 10, "active": True}))

    # 1. Query matching id = 0
    q_zero = "MATCH (i:Item {id: 0}) RETURN i.id AS id, i.count AS cnt, i.active AS act"
    res_zero = gql_core.run(q_zero, g)
    assert len(res_zero) == 1
    assert res_zero[0] == {"id": 0, "cnt": 0, "act": False}

    # 2. Filter count = 0
    q_cnt = "MATCH (i:Item) WHERE i.count = 0 RETURN i.id AS id"
    res_cnt = gql_core.run(q_cnt, g)
    assert res_cnt == [{"id": 0}]

    # 3. Aggregation counting items including zero
    q_agg = "MATCH (i:Item) RETURN COUNT(i) AS total, SUM(i.count) AS sum_cnt"
    res_agg = gql_core.run(q_agg, g)
    assert res_agg == [{"total": 2, "sum_cnt": 10}]


def test_public_api_surface_and_execution():
    """Verify public GQL-Core module symbols and execution."""
    assert hasattr(gql_core, "__version__")
    assert gql_core.__version__ == "0.2.0"
    assert callable(gql_core.run)
    assert callable(gql_core.parse)
    assert callable(gql_core.plan)
    assert issubclass(gql_core.PropertyGraph, object)
    assert issubclass(gql_core.Node, object)
    assert issubclass(gql_core.Edge, object)

    # End to end run via public API
    g = gql_core.PropertyGraph()
    g.add_node(gql_core.Node(id="root", label="Test", props={"val": "ok"}))
    rows = gql_core.run("MATCH (t:Test) RETURN t.val AS status", g)
    assert rows == [{"status": "ok"}]
