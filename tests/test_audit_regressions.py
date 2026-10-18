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
    assert gql_core.__version__.startswith("0.2.0")
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


# ═══════════════════════════════════════════════════════════════════════
# MISSION AUDIT REGRESSIONS
# ═══════════════════════════════════════════════════════════════════════


def test_diamond_graph_exact_two_hops():
    """Reproduce the diamond graph:
    A -> C
    A -> B
    B -> C
    An exact-two-hop query from A must reach C through A-B-C.
    """
    g = PropertyGraph()
    g.add_node(Node(id="A", label="Node"))
    g.add_node(Node(id="B", label="Node"))
    g.add_node(Node(id="C", label="Node"))
    g.add_edge(Edge(id="e_ac", label="REL", src="A", dst="C"))
    g.add_edge(Edge(id="e_ab", label="REL", src="A", dst="B"))
    g.add_edge(Edge(id="e_bc", label="REL", src="B", dst="C"))

    # 1. Exact 2-hop query from A must reach C via A-B-C
    q2 = "MATCH (a:Node {id: 'A'})-[:REL*2..2]->(c:Node) RETURN c.id AS id"
    res2 = gql_core.run(q2, g)
    assert res2 == [{"id": "C"}], f"Expected C via A-B-C, got {res2}"

    # 2. Exact 1-hop query from A reaches B and C
    q1 = "MATCH (a:Node {id: 'A'})-[:REL*1..1]->(x:Node) RETURN x.id AS id ORDER BY id ASC"
    res1 = gql_core.run(q1, g)
    assert res1 == [{"id": "B"}, {"id": "C"}]

    # 3. Bounded range 1..2 hops reaches B (1-hop), C (1-hop), and C (2-hop)
    q12 = "MATCH (a:Node {id: 'A'})-[:REL*1..2]->(x:Node) RETURN x.id AS id ORDER BY id ASC"
    res12 = gql_core.run(q12, g)
    assert res12 == [{"id": "B"}, {"id": "C"}, {"id": "C"}], f"Expected multiple paths to C, got {res12}"


def test_path_traversal_cycles_and_parallel_edges():
    """Verify cycles, parallel edges, trail uniqueness, and repeated endpoints."""
    g = PropertyGraph()
    # Cycle: A -[e1]-> B -[e2]-> C -[e3]-> A
    # Parallel edge between A and B: A -[e4]-> B
    g.add_node(Node(id="A", label="N"))
    g.add_node(Node(id="B", label="N"))
    g.add_node(Node(id="C", label="N"))
    g.add_edge(Edge(id="e1", label="REL", src="A", dst="B"))
    g.add_edge(Edge(id="e2", label="REL", src="B", dst="C"))
    g.add_edge(Edge(id="e3", label="REL", src="C", dst="A"))
    g.add_edge(Edge(id="e4", label="REL", src="A", dst="B"))

    # 1. Parallel edges from A to B: 2 distinct paths of length 1
    q_par = "MATCH (a:N {id: 'A'})-[:REL*1..1]->(b:N) RETURN b.id AS id"
    res_par = gql_core.run(q_par, g)
    assert len(res_par) == 2
    assert all(r["id"] == "B" for r in res_par)

    # 2. Repeated endpoints: cycle returns to start node A at length 3
    q_cycle = "MATCH (a:N {id: 'A'})-[:REL*3..3]->(x:N) RETURN x.id AS id"
    res_cycle = gql_core.run(q_cycle, g)
    # A->B->C->A (via e1-e2-e3 or e4-e2-e3) reaches A twice
    assert len(res_cycle) == 2
    assert all(r["id"] == "A" for r in res_cycle)

    # 3. Trail uniqueness: no relationship can be repeated
    # In a graph of 4 edges, a 5-hop path would require repeating an edge.
    q_trail = "MATCH (a:N {id: 'A'})-[:REL*5..5]->(x:N) RETURN x.id AS id"
    assert gql_core.run(q_trail, g) == []


def test_networkx_adapter_integer_vs_string_identities():
    """Verify NetworkX integer ID 1 and string ID '1' are preserved distinctly without collision."""
    import networkx as nx

    G = nx.Graph()
    G.add_node(1, name="int_node")
    G.add_node("1", name="str_node")
    G.add_edge(1, "1", label="CONNECTED_TO")

    graph = PropertyGraph.from_networkx(G)
    assert len(graph) == 2
    assert graph.get_node(1).props["name"] == "int_node"
    assert graph.get_node("1").props["name"] == "str_node"

    # Query matching integer 1
    r_int = gql_core.run("MATCH (n:Node) WHERE n.id = 1 RETURN n.name AS name", graph)
    assert r_int == [{"name": "int_node"}]

    # Query matching string '1'
    r_str = gql_core.run("MATCH (n:Node) WHERE n.id = '1' RETURN n.name AS name", graph)
    assert r_str == [{"name": "str_node"}]


def test_adapter_record_id_zero_and_falsy_properties():
    """Verify Record ID 0, falsy property values, and duplicate collision rejection."""
    nodes = [
        {"id": 0, "name": "NodeZero", "active": False, "score": 0, "notes": "", "tags": []},
        {"id": 1, "name": "NodeOne", "active": True, "score": 10},
    ]
    edges = [
        {"src": 0, "dst": 1, "label": "POINTS_TO", "weight": 0}
    ]
    graph = PropertyGraph.from_records(nodes, edges)

    # Record ID 0 is not falsy
    n0 = graph.get_node(0)
    assert n0 is not None
    assert n0.id == 0
    assert n0.props["name"] == "NodeZero"
    assert n0.props["active"] is False
    assert n0.props["score"] == 0
    assert n0.props["notes"] == ""
    assert n0.props["tags"] == []

    # Edge weight 0 is preserved
    e = graph.get_edge("POINTS_TO:0:1:0")
    assert e is not None
    assert e.props["weight"] == 0


def test_adapter_empty_missing_and_duplicate_rejection():
    """Verify empty/missing identifiers and duplicate identifier collisions raise ValueError."""
    # 1. Missing identifier in node record
    with pytest.raises(ValueError, match="missing identifier or identifier is empty"):
        PropertyGraph.from_records([{"name": "No ID"}])

    # 2. Empty string identifier
    with pytest.raises(ValueError, match="missing identifier or identifier is empty"):
        PropertyGraph.from_records([{"id": "", "name": "Empty ID"}])

    # 3. None identifier
    with pytest.raises(ValueError, match="missing identifier or identifier is empty"):
        PropertyGraph.from_records([{"id": None, "name": "None ID"}])

    # 4. Duplicate identifier collision in records
    with pytest.raises(ValueError, match="Duplicate node identifier collision"):
        PropertyGraph.from_records([
            {"id": "user1", "name": "Alice"},
            {"id": "user1", "name": "Bob"},
        ])

    # 5. Missing edge endpoints
    with pytest.raises(ValueError, match="Edge record missing"):
        PropertyGraph.from_records(
            [{"id": "A"}, {"id": "B"}],
            [{"src": "", "dst": "B"}]
        )


def test_multigraph_parallel_edges():
    """Verify NetworkX MultiDiGraph preserves parallel edges between same endpoints."""
    import networkx as nx

    G = nx.MultiDiGraph()
    G.add_node("A")
    G.add_node("B")
    G.add_edge("A", "B", key="e1", label="CALLS", count=1)
    G.add_edge("A", "B", key="e2", label="CALLS", count=2)

    graph = PropertyGraph.from_networkx(G)
    assert len(graph) == 2
    assert len(graph._edges) == 2

    rows = gql_core.run("MATCH (a)-[r:CALLS]->(b) RETURN r.count AS cnt ORDER BY cnt ASC", graph)
    assert rows == [{"cnt": 1}, {"cnt": 2}]


def test_three_valued_logic_null_semantics():
    """Verify openCypher three-valued logic (3VL) null semantics.
    Test:
      MATCH (n)
      WHERE NOT n.x = 2
      RETURN n
    Includes nodes with x=2, x=4, x=null, and missing x.
    """
    g = PropertyGraph()
    g.add_node(Node(id="n1", label="Item", props={"x": 2}))
    g.add_node(Node(id="n2", label="Item", props={"x": 4}))
    g.add_node(Node(id="n3", label="Item", props={"x": None}))  # x is explicitly null
    g.add_node(Node(id="n4", label="Item", props={}))            # x is missing

    # 1. NOT n.x = 2
    # n1: 2 = 2 is True  -> NOT True is False -> EXCLUDED
    # n2: 4 = 2 is False -> NOT False is True  -> INCLUDED
    # n3: null = 2 is Unknown -> NOT Unknown is Unknown -> EXCLUDED
    # n4: null = 2 is Unknown -> NOT Unknown is Unknown -> EXCLUDED
    q = "MATCH (n:Item) WHERE NOT n.x = 2 RETURN n.id AS id"
    res = gql_core.run(q, g)
    assert res == [{"id": "n2"}], f"Expected only n2 (x=4), got {res}"

    # 2. n.x = 2 matches only n1
    q_eq = "MATCH (n:Item) WHERE n.x = 2 RETURN n.id AS id"
    assert gql_core.run(q_eq, g) == [{"id": "n1"}]

    # 3. Kleene OR logic: True OR Unknown evaluates to True
    q_or = "MATCH (n:Item) WHERE n.x = 4 OR n.x = 999 RETURN n.id AS id"
    assert gql_core.run(q_or, g) == [{"id": "n2"}]

    # 4. Kleene AND logic: False AND Unknown evaluates to False; True AND Unknown is Unknown
    q_and = "MATCH (n:Item) WHERE n.x = 4 AND n.x > 0 RETURN n.id AS id"
    assert gql_core.run(q_and, g) == [{"id": "n2"}]

