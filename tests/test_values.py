"""Grounding string literals to stored values (gql_core.ground_values)."""

from gql_core import Edge, Node, PropertyGraph, ground_values, run


def _graph() -> PropertyGraph:
    g = PropertyGraph()
    for i, name in enumerate(["swingman", "center", "shooting guard"]):
        g.add_node(Node(f"pos{i}", "Position", {"name": name}))
    g.add_node(Node("p1", "Player", {"name": "Ann"}))
    g.add_node(Node("p2", "Player", {"name": "ANN"}))  # two players whose names differ only in case
    g.add_node(Node("p3", "Player", {"name": "Bob"}))
    g.add_edge(Edge("e1", "playsPosition", "p1", "pos0"))
    g.add_edge(Edge("e2", "playsPosition", "p3", "pos2"))
    return g


def gv(q: str) -> str:
    return ground_values(q, _graph()).query


def test_where_equality_inline_map_and_in_list():
    assert gv("MATCH (p:Position) WHERE p.name = 'Swingman' RETURN p") == \
        "MATCH (p:Position) WHERE p.name = 'swingman' RETURN p"
    assert gv('MATCH (:Player)-[:playsPosition]->(p:Position {name: "Shooting  Guard"}) RETURN p') == \
        'MATCH (:Player)-[:playsPosition]->(p:Position {name: "shooting guard"}) RETURN p'
    assert gv("MATCH (p:Position) WHERE p.name IN ['Center', 'Point guard'] RETURN p") == \
        "MATCH (p:Position) WHERE p.name IN ['center', 'Point guard'] RETURN p"
    assert gv("MATCH (p:Position) WHERE 'CENTER' = p.name RETURN p") == "MATCH (p:Position) WHERE 'center' = p.name RETURN p"


def test_label_from_elsewhere_in_query():
    assert gv("MATCH (x:Player)-->(p:Position) WITH p MATCH (p) WHERE p.name = 'Center' RETURN p") == \
        "MATCH (x:Player)-->(p:Position) WITH p MATCH (p) WHERE p.name = 'center' RETURN p"


def test_leaves_exact_ambiguous_unlabelled_and_fuzzy_cases_alone():
    for q in [
        "MATCH (p:Position) WHERE p.name = 'center' RETURN p",           # exact
        "MATCH (p:Player {name: 'ann'}) RETURN p",                       # 'Ann' and 'ANN' both stored
        "MATCH (x) WHERE x.name = 'Center' RETURN x",                    # no label
        "MATCH (p:Position) WHERE p.name = 'Centre' RETURN p",           # not a case variant
        "MATCH (p:Position) WHERE p.name CONTAINS 'Guard' RETURN p",     # not an equality
        "MATCH (p:Position) WHERE p.nickname = 'Center' RETURN p",       # property never stored
        "not a query",
    ]:
        r = ground_values(q, _graph())
        assert r.query == q and not r.changed, q


def test_quotes_inside_value_are_escaped():
    g = PropertyGraph()
    g.add_node(Node("m", "Movie", {"name": "Dead Men Don't Wear Plaid"}))
    r = ground_values(r"MATCH (m:Movie {name: 'dead men don\'t wear plaid'}) RETURN m.name AS n", g)
    assert r.changed
    assert run(r.query, g) == [{"n": "Dead Men Don't Wear Plaid"}]


def test_grounded_query_returns_the_answer():
    g = _graph()
    q = "MATCH (p:Player)-[:playsPosition]->(:Position {name: 'Swingman'}) RETURN p.name AS n"
    assert run(q, g) == []
    r = ground_values(q, g)
    assert r.changes == ["name 'Swingman' -> 'swingman' (stored value for Position)"]
    assert run(r.query, g) == [{"n": "Ann"}]
