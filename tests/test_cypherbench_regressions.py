"""Regressions found by running CypherBench gold queries on GQL-Core."""

from gql_core import Edge, Node, PropertyGraph, run
from gql_core.query.parser import parse


def _graph() -> PropertyGraph:
    g = PropertyGraph()
    g.add_node(Node("t1", "Team", {"name": "Kings"}))
    g.add_node(Node("t2", "Team", {"name": "Bulls"}))
    g.add_node(Node("p1", "Player", {"name": "Ann", "mass_kg": 80.0}))
    g.add_node(Node("p2", "Player", {"name": "Bob"}))  # mass unknown
    g.add_node(Node("p3", "Player", {"name": "Cid", "mass_kg": 70.0}))
    g.add_edge(Edge("e1", "playsFor", "p1", "t1"))
    g.add_edge(Edge("e2", "playsFor", "p2", "t1"))
    g.add_edge(Edge("e3", "playsFor", "p2", "t2"))
    g.add_edge(Edge("e4", "playsFor", "p3", "t2"))
    return g


def test_call_subquery_union_then_distinct_count():
    q = ("CALL { MATCH (n:Player)-[r0:playsFor]->(m0:Team {name: 'Kings'}) RETURN n, m0 as m "
         "UNION MATCH (n:Player)-[r1:playsFor]->(m1:Team {name: 'Bulls'}) RETURN n, m1 as m } "
         "WITH DISTINCT n RETURN count(n)")
    assert run(q, _graph()) == [{"count(n)": 3}]


def test_call_subquery_returns_usable_node_bindings():
    q = ("CALL { MATCH (n:Player)-[:playsFor]->(:Team {name: 'Bulls'}) RETURN n } "
         "RETURN n.name AS name ORDER BY name")
    assert run(q, _graph()) == [{"name": "Bob"}, {"name": "Cid"}]


def test_correlated_call_subquery():
    rows = run("UNWIND [1, 2] AS x CALL { WITH x RETURN x * 10 AS y } RETURN x, y", PropertyGraph())
    assert rows == [{"x": 1, "y": 10}, {"x": 2, "y": 20}]


def test_uncorrelated_call_subquery_is_cross_product():
    rows = run("UNWIND [1, 2] AS x CALL { RETURN 5 AS y UNION RETURN 6 AS y } RETURN x, y", PropertyGraph())
    assert sorted((r["x"], r["y"]) for r in rows) == [(1, 5), (1, 6), (2, 5), (2, 6)]


def test_keywords_are_case_insensitive():
    g = _graph()
    upper = run("MATCH (n:Player) WHERE n.mass_kg > 75 RETURN n.name AS x ORDER BY x DESC LIMIT 5", g)
    lower = run("match (n:Player) where n.mass_kg > 75 return n.name as x order by x desc limit 5", g)
    assert upper == lower == [{"x": "Ann"}]


def test_keyword_prefixed_property_names_still_parse():
    q = parse("MATCH (n) RETURN n.order AS o, n.end_year, n.in_league")
    assert [p.expr.prop for p in q.clauses[-1].items] == ["order", "end_year", "in_league"]


def test_order_by_null_property_after_with_sorts_as_null():
    # Neo4j: nulls sort last ascending, first descending. A missing property must not
    # fall back to sorting by the node object itself.
    g = _graph()
    asc = run("MATCH (n:Player) WITH DISTINCT n RETURN n.name ORDER BY n.mass_kg ASC", g)
    desc = run("MATCH (n:Player) WITH DISTINCT n RETURN n.name ORDER BY n.mass_kg DESC", g)
    assert [r["n.name"] for r in asc] == ["Cid", "Ann", "Bob"]
    assert [r["n.name"] for r in desc] == ["Bob", "Ann", "Cid"]


def test_chained_comparison_not_affected_by_earlier_parses():
    # Parenthesized-expression markers are object ids; they must be reset per parse.
    for _ in range(200):
        parse("RETURN (1 < 2) = true AS p")
    assert run("RETURN 1 < 2 = 2 <> 3 AS chained", PropertyGraph())[0]["chained"] is True


# ── Planner: start from the constrained node, wherever it is in the pattern ────

import random
import time

from gql_core.query import executor as _ex


def _industry_graph(companies: int = 3000, industries: int = 40, seed: int = 1) -> PropertyGraph:
    rnd = random.Random(seed)
    g = PropertyGraph()
    for i in range(industries):
        g.add_node(Node(f"i{i}", "Industry", {"name": f"Ind{i}"}))
    e = 0
    for c in range(companies):
        g.add_node(Node(f"c{c}", "Company", {"name": f"Co{c}"}))
        for i in rnd.sample(range(industries), 3):
            g.add_edge(Edge(f"e{e}", "operatesIn", f"c{c}", f"i{i}"))
            e += 1
    return g


def _rows_key(rows):
    return sorted(repr(sorted((k, getattr(v, "id", v)) for k, v in r.items() if not k.startswith("__"))) for r in rows)


def test_far_end_anchor_gives_same_rows_as_left_to_right():
    g = _industry_graph(companies=300)
    patterns = [
        "MATCH (n:Company)-[r0:operatesIn]->(m0:Industry)<-[r1:operatesIn]-(m1:Company {name: 'Co7'}) RETURN n, r0, m0, r1, m1",
        "MATCH (n:Company)-[:operatesIn]->(m0:Industry {name: 'Ind3'})<-[:operatesIn]-(m1:Company) RETURN n, m0, m1",
        "MATCH (n)-->(:Industry)<--(:Company {name: 'Co7'}) RETURN n",
        "MATCH (n:Company)-[:operatesIn]-(m0)-[:operatesIn]-(m1 {name: 'Co7'}) RETURN n, m0",
    ]
    for q in patterns:
        pat = parse(q).clauses[0].patterns[0]
        assert _ex._choose_anchor(pat, {}, g) > 0, q
        reordered = _ex._match_path_pattern(pat, {}, g)
        linear = _ex._match_linear(pat, {}, g)
        assert reordered and _rows_key(reordered) == _rows_key(linear), q


def test_anchor_not_moved_when_filter_depends_on_earlier_node():
    g = _industry_graph(companies=50)
    pat = parse("MATCH (a:Company)-->(i:Industry)<--(b:Company {name: a.name}) RETURN a").clauses[0].patterns[0]
    assert _ex._choose_anchor(pat, {}, g) == 0


def test_far_end_anchor_is_fast_on_large_graph():
    g = _industry_graph(companies=20000)
    q = ("MATCH (n:Company)-[r0:operatesIn]->(m0:Industry)<-[r1:operatesIn]-(m1:Company {name: 'Co7'}) "
         "WITH DISTINCT n RETURN count(n) AS c")
    t = time.perf_counter()
    rows = run(q, g)
    assert time.perf_counter() - t < 10
    co7 = {e.dst for e in g._edges.values() if e.src == "c7"}
    # Relationship uniqueness: r0 and r1 must differ, so c7 itself (one edge per industry) is excluded.
    expected = len({e.src for e in g._edges.values() if e.dst in co7} - {"c7"})
    assert rows == [{"c": expected}]


def test_both_ends_bound_starts_from_lower_degree_node():
    # (n:Country)<-[:originatesFrom]-(m0:Movie),(n)<-[:releasedIn]-(m0): in the second
    # pattern both ends are bound; walk from the movie (few edges), not the country.
    g = PropertyGraph()
    g.add_node(Node("usa", "Country", {"name": "USA"}))
    g.add_node(Node("fr", "Country", {"name": "France"}))
    e = 0
    for i in range(20000):
        g.add_node(Node(f"m{i}", "Movie", {"name": f"M{i}"}))
        g.add_edge(Edge(f"e{e}", "originatesFrom", f"m{i}", "usa")); e += 1
        g.add_edge(Edge(f"e{e}", "releasedIn", f"m{i}", "usa" if i % 2 else "fr")); e += 1
    q = ("MATCH (n:Country)<-[r0:originatesFrom]-(m0:Movie),(n:Country)<-[r1:releasedIn]-(m0:Movie) "
         "WITH DISTINCT n RETURN count(DISTINCT n) AS c")
    t = time.perf_counter()
    assert run(q, g) == [{"c": 1}]
    assert time.perf_counter() - t < 10


def test_where_equality_chooses_start_node_and_keeps_results():
    g = _industry_graph(companies=300)
    queries = [
        "MATCH (c1:Company)-[r:operatesIn]->(i1:Industry)<-[r2:operatesIn]-(c2:Company) "
        "WHERE c2.name = 'Co7' RETURN c1.name AS a, i1.name AS i",
        "MATCH (c:Company)-[:operatesIn]->(i:Industry) WHERE i.name IN ['Ind1', 'Ind2'] AND c.name <> 'Co3' "
        "RETURN c.name AS a, i.name AS i",
        "MATCH (c1:Company)-->(i:Industry)<--(c2:Company) WHERE c2.name = 'Co7' OR c2.name = 'Co8' "
        "RETURN c1.name AS a",
        "MATCH (c1:Company)-->(i:Industry)<--(c2:Company) WHERE c2.name = 7 RETURN c1.name AS a",
    ]
    for q in queries:
        clause = parse(q).clauses[0]
        hints = _ex._where_equality_hints(clause.where)
        pat = clause.patterns[0]
        fast = _ex._match_path_pattern(pat, {}, g, hints)
        slow = _ex._match_linear(pat, {}, g)
        keep = [m for m in slow if _ex._eval_single_expr(clause.where, m, g) is True]
        got = [m for m in fast if _ex._eval_single_expr(clause.where, m, g) is True]
        assert _rows_key(got) == _rows_key(keep), q
        assert bool(keep) == ("= 7" not in q), q  # type-mismatched equality matches nothing


def test_where_equality_on_far_node_is_fast_on_large_graph():
    g = _industry_graph(companies=20000)
    q = ("MATCH (c1:Company)-[r:operatesIn]->(i1:Industry)<-[r2:operatesIn]-(c2:Company) "
         "WHERE c2.name = 'Co7' RETURN count(DISTINCT c1) AS c")
    t = time.perf_counter()
    rows = run(q, g)
    assert time.perf_counter() - t < 10
    co7 = {e.dst for e in g._edges.values() if e.src == "c7"}
    assert rows == [{"c": len({e.src for e in g._edges.values() if e.dst in co7} - {"c7"})}]
