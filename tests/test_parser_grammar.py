"""Grammar / parser tests — lexical and structural correctness only."""

from __future__ import annotations

import pytest

from query.ast import And, Comparison, NodePat, Or, Projection, Query, Ref, RelPat
from query.parser import parse, parse_tree


def test_parse_minimal_query():
    q = parse("MATCH (p:Player) RETURN p.name")
    assert isinstance(q, Query)
    assert q.patterns[0].nodes[0] == NodePat(var="p", label="Player", filters=())
    assert q.projections[0].expr == Ref(var="p", prop="name")
    assert q.where is None
    assert q.order_by is None
    assert q.limit is None


def test_parse_inline_property_filter():
    q = parse('MATCH (p:Player {country: "PAK"}) RETURN p.name')
    assert q.patterns[0].nodes[0].filters == (("country", "PAK"),)


def test_parse_quantifier_star():
    q = parse("MATCH (a)-[:NEXT_DELIVERY*]->(b) RETURN a")
    rel = q.patterns[0].rels[0]
    assert rel.quantifier == ("star", None)
    assert rel.direction == "out"


def test_parse_quantifier_plus():
    q = parse("MATCH (a)-[:NEXT_DELIVERY+]->(b) RETURN a")
    assert q.patterns[0].rels[0].quantifier == ("plus",)


def test_parse_quantifier_exactly():
    q = parse("MATCH (a)-[:NEXT_DELIVERY*3]->(b) RETURN a")
    assert q.patterns[0].rels[0].quantifier == ("exactly", 3)


def test_parse_quantifier_range():
    q = parse("MATCH (a)-[:NEXT_DELIVERY*1..3]->(b) RETURN a")
    assert q.patterns[0].rels[0].quantifier == ("range", 1, 3)


def test_parse_undirected_edge():
    q = parse("MATCH (a)-[:TEAMMATES_WITH]-(b) RETURN a")
    assert q.patterns[0].rels[0].direction == "undirected"


def test_parse_reverse_edge():
    q = parse("MATCH (a)<-[:BATTED_IN]-(b) RETURN a")
    assert q.patterns[0].rels[0].direction == "in"


def test_parse_edge_variable_binding():
    q = parse("MATCH (p)-[r:BATTED_IN]->(m) RETURN r")
    assert q.patterns[0].rels[0].var == "r"
    assert q.patterns[0].rels[0].label == "BATTED_IN"


def test_parse_where_and_or_not():
    q = parse(
        'MATCH (p:Player) WHERE p.country = "PAK" AND NOT p.role = "wk" RETURN p.name'
    )
    assert isinstance(q.where, And)
    assert isinstance(q.where.children[0], Comparison)


def test_parse_aggregations():
    for agg in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
        q = parse(f"MATCH (p:Player) RETURN {agg}(p) AS x")
        assert q.projections[0].agg == agg
        assert q.projections[0].alias == "x"


def test_parse_order_by_limit():
    q = parse("MATCH (p:Player) RETURN p.name ORDER BY p.name DESC LIMIT 10")
    assert q.order_by.direction == "DESC"
    assert q.limit == 10


def test_parse_multi_pattern():
    q = parse(
        "MATCH (p:Player)-[:BATTED_IN]->(m:Match), (p)-[:CAPTAINED]->(m) RETURN p.name"
    )
    assert len(q.patterns) == 2


def test_parse_tree_pretty_print():
    text = parse_tree("MATCH (p:Player) RETURN p.name")
    assert "match_clause" in text
    assert "Player" in text


def test_parse_invalid_raises():
    with pytest.raises(Exception):
        parse("RETURN 42")
