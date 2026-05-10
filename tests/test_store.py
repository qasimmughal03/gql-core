from __future__ import annotations

import pytest

from graph.store import Edge, Node, PropertyGraph


def _seed_two_players(g: PropertyGraph) -> None:
    g.add_node(Node(id="p1", label="Player", props={"name": "A"}))
    g.add_node(Node(id="p2", label="Player", props={"name": "B"}))


def test_add_node_idempotent_merges_props():
    g = PropertyGraph()
    g.add_node(Node(id="p1", label="Player", props={"name": "A"}))
    g.add_node(Node(id="p1", label="Player", props={"country": "PAK"}))
    assert g.get_node("p1").props == {"name": "A", "country": "PAK"}
    assert g.stats()["nodes"] == 1
    assert g.stats()["by_label"]["Player"] == 1


def test_add_node_relabel_raises():
    g = PropertyGraph()
    g.add_node(Node(id="x1", label="Player"))
    with pytest.raises(ValueError):
        g.add_node(Node(id="x1", label="Match"))


def test_add_edge_creates_bidirectional_index():
    g = PropertyGraph()
    _seed_two_players(g)
    g.add_edge(Edge(id="e1", label="TEAMMATES_WITH", src="p1", dst="p2"))
    assert "e1" in g._out["p1"]
    assert "e1" in g._in["p2"]
    assert g.stats()["edges_by_label"]["TEAMMATES_WITH"] == 1


def test_add_edge_unknown_endpoint_raises():
    g = PropertyGraph()
    g.add_node(Node(id="p1", label="Player"))
    with pytest.raises(KeyError):
        g.add_edge(Edge(id="e1", label="X", src="p1", dst="missing"))


def test_add_edge_idempotent_merges_props():
    g = PropertyGraph()
    _seed_two_players(g)
    g.add_edge(
        Edge(id="e1", label="TEAMMATES_WITH", src="p1", dst="p2", props={"match_count": 1})
    )
    g.add_edge(
        Edge(id="e1", label="TEAMMATES_WITH", src="p1", dst="p2", props={"match_count": 2})
    )
    assert g.get_edge("e1").props == {"match_count": 2}
    assert g.stats()["edges"] == 1


def test_neighbors_filters_by_label_and_direction():
    g = PropertyGraph()
    g.add_node(Node(id="p", label="Player"))
    g.add_node(Node(id="m1", label="Match"))
    g.add_node(Node(id="m2", label="Match"))
    g.add_edge(Edge(id="b1", label="BATTED_IN", src="p", dst="m1"))
    g.add_edge(Edge(id="c1", label="CAPTAINED", src="p", dst="m2"))
    out_batted = list(g.neighbors("p", label="BATTED_IN", direction="out"))
    assert len(out_batted) == 1
    assert out_batted[0][1].id == "m1"
    out_all = list(g.neighbors("p", direction="out"))
    assert {n.id for _, n in out_all} == {"m1", "m2"}
    in_batted_to_m1 = list(g.neighbors("m1", direction="in"))
    assert len(in_batted_to_m1) == 1
    assert in_batted_to_m1[0][1].id == "p"


def test_neighbors_invalid_direction_raises():
    g = PropertyGraph()
    g.add_node(Node(id="p1", label="Player"))
    with pytest.raises(ValueError):
        list(g.neighbors("p1", direction="sideways"))


def test_nodes_by_label_returns_only_matching():
    g = PropertyGraph()
    g.add_node(Node(id="p1", label="Player"))
    g.add_node(Node(id="p2", label="Player"))
    g.add_node(Node(id="m1", label="Match"))
    players = {n.id for n in g.nodes_by_label("Player")}
    matches = {n.id for n in g.nodes_by_label("Match")}
    assert players == {"p1", "p2"}
    assert matches == {"m1"}
    assert list(g.nodes_by_label("Phantom")) == []


def test_edges_by_label_returns_only_matching():
    g = PropertyGraph()
    _seed_two_players(g)
    g.add_node(Node(id="m1", label="Match"))
    g.add_edge(Edge(id="b1", label="BATTED_IN", src="p1", dst="m1"))
    g.add_edge(Edge(id="t1", label="TEAMMATES_WITH", src="p1", dst="p2"))
    assert {e.id for e in g.edges_by_label("BATTED_IN")} == {"b1"}
    assert {e.id for e in g.edges_by_label("TEAMMATES_WITH")} == {"t1"}


def test_stats_reports_counts_for_empty_and_populated():
    g = PropertyGraph()
    assert g.stats() == {"nodes": 0, "edges": 0, "by_label": {}, "edges_by_label": {}}
    _seed_two_players(g)
    g.add_edge(Edge(id="e1", label="TEAMMATES_WITH", src="p1", dst="p2"))
    s = g.stats()
    assert s["nodes"] == 2
    assert s["edges"] == 1
    assert s["by_label"]["Player"] == 2
    assert s["edges_by_label"]["TEAMMATES_WITH"] == 1
    assert len(g) == 2
