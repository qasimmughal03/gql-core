"""Schema-based relationship direction correction (gql_core.correct_relationship_directions)."""

from gql_core import (
    Edge,
    Node,
    PropertyGraph,
    ask,
    correct_relationship_directions,
    run,
    schema_triples,
)

SCHEMA = {
    ("written_by", "Movie", "Person"),
    ("directed_by", "Movie", "Person"),
    ("has_genre", "Movie", "Genre"),
    ("knows", "Person", "Person"),
}


def fix(q: str) -> str:
    return correct_relationship_directions(q, SCHEMA).query


def _graph() -> PropertyGraph:
    g = PropertyGraph()
    g.add_node(Node("m1", "Movie", {"name": "Blow Out"}))
    g.add_node(Node("m2", "Movie", {"name": "Dressed to Kill"}))
    g.add_node(Node("p1", "Person", {"name": "Brian De Palma"}))
    g.add_node(Node("g1", "Genre", {"name": "Thriller"}))
    g.add_edge(Edge("e1", "written_by", "m1", "p1"))
    g.add_edge(Edge("e2", "written_by", "m2", "p1"))
    g.add_edge(Edge("e3", "has_genre", "m1", "g1"))
    return g


def test_reverses_an_impossible_outgoing_arrow():
    r = correct_relationship_directions("MATCH (p:Person {name: 'X'})-[:written_by]->(m:Movie) RETURN m.name", SCHEMA)
    assert r.query == "MATCH (p:Person {name: 'X'})<-[:written_by]-(m:Movie) RETURN m.name"
    assert r.changed and "written_by" in r.changes[0]


def test_reverses_an_impossible_incoming_arrow():
    assert fix("MATCH (m:Movie)<-[r:directed_by]-(p:Person) RETURN p") == "MATCH (m:Movie)-[r:directed_by]->(p:Person) RETURN p"


def test_fixes_only_the_wrong_hop_in_a_chain():
    q = "MATCH (m:Movie {name: 'Dressed to Kill'})-[:written_by]->(p:Person)-[:written_by]->(o:Movie) RETURN o.name"
    assert fix(q) == ("MATCH (m:Movie {name: 'Dressed to Kill'})-[:written_by]->(p:Person)<-[:written_by]-(o:Movie) "
                      "RETURN o.name")


def test_uses_labels_declared_elsewhere_in_the_query():
    assert fix("MATCH (p:Person) WITH p MATCH (p)-[:written_by]->(m) RETURN m") == \
        "MATCH (p:Person) WITH p MATCH (p)<-[:written_by]-(m) RETURN m"


def test_inside_exists_subquery():
    assert fix("MATCH (p:Person) WHERE EXISTS { (p)-[:directed_by]->(:Movie) } RETURN p") == \
        "MATCH (p:Person) WHERE EXISTS { (p)<-[:directed_by]-(:Movie) } RETURN p"


def test_leaves_valid_ambiguous_undirected_and_unknown_relationships_alone():
    for q in [
        "MATCH (m:Movie)-[:written_by]->(p:Person) RETURN p",      # already right
        "MATCH (a:Person)-[:knows]->(b:Person) RETURN a",           # both directions allowed
        "MATCH (p:Person)-[:written_by]-(m) RETURN m",              # undirected
        "MATCH (g:Genre)<-[:written_by]-(p:Person) RETURN g",       # wrong both ways: not a direction error
        "MATCH (p:Person)-[:acted_in]->(m:Movie) RETURN m",         # type not in schema
        "MATCH (a)-[:written_by]->(b) RETURN a",                    # no labels to judge by
        "MATCH (p:Person)-->(m:Movie) RETURN m",                    # untyped
        "not a query at all",
    ]:
        r = correct_relationship_directions(q, SCHEMA)
        assert r.query == q and not r.changed, q


def test_rest_of_the_query_text_is_untouched():
    q = "MATCH (p:Person {name: \"A -[:x]-> B\"})-[:written_by]->(m:Movie)  // note\nRETURN m.name AS `t`"
    assert fix(q) == "MATCH (p:Person {name: \"A -[:x]-> B\"})<-[:written_by]-(m:Movie)  // note\nRETURN m.name AS `t`"


def test_schema_from_graph_and_cypherbench_dict():
    assert schema_triples(_graph()) == {("written_by", "Movie", "Person"), ("has_genre", "Movie", "Genre")}
    d = {"relations": [{"label": "written_by", "subj_label": "Movie", "obj_label": "Person"}]}
    assert schema_triples(d) == {("written_by", "Movie", "Person")}


def test_schema_from_graph_counts_every_label():
    g = PropertyGraph()
    g.add_node(Node("m", "Movie", {"name": "Hold Back the Dawn"}))
    g.add_node(Node("y", "Movie", {"name": "1941"}, labels=("Movie", "Year")))
    g.add_edge(Edge("e", "release_year", "m", "y"))
    assert ("release_year", "Movie", "Year") in schema_triples(g)


def test_corrected_query_returns_the_answer():
    g = _graph()
    wrong = "MATCH (p:Person {name: 'Brian De Palma'})-[:written_by]->(m:Movie) RETURN m.name AS m ORDER BY m"
    assert run(wrong, g) == []
    assert run(correct_relationship_directions(wrong, g).query, g) == [{"m": "Blow Out"}, {"m": "Dressed to Kill"}]


def test_ask_corrects_directions_by_default():
    g = _graph()
    llm = lambda prompt: "MATCH (p:Person {name: 'Brian De Palma'})-[:written_by]->(m:Movie) RETURN count(m) AS n"  # noqa: E731
    assert ask(g, "How many films did Brian De Palma write?", client=llm) == [{"n": 2}]
    assert ask(g, "How many films did Brian De Palma write?", client=llm, correct_directions=False) == [{"n": 0}]
