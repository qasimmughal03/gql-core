from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from graph.store import PropertyGraph
from ingestion import ids
from ingestion.cricsheet_parser import CricsheetParser
from ingestion.validator import ShapeValidator

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
SHAPES = ROOT / "ontology" / "shapes.yaml"
GROUND_TRUTH = json.loads((ROOT / "tests" / "ground_truth.json").read_text())


@pytest.fixture(scope="module")
def validator() -> ShapeValidator:
    return ShapeValidator(SHAPES)


def _fresh_graph_for(filename: str, validator: ShapeValidator) -> PropertyGraph:
    g = PropertyGraph()
    p = CricsheetParser(g, validator)
    p.ingest_file(FIXTURES / filename)
    return g


def _full_corpus_graph(validator: ShapeValidator) -> PropertyGraph:
    g = PropertyGraph()
    p = CricsheetParser(g, validator)
    for f in sorted(FIXTURES.glob("*.json")):
        p.ingest_file(f)
    return g


# ── Per-fixture ground-truth checks ──────────────────────────────────


@pytest.mark.parametrize("fid", sorted(GROUND_TRUTH["per_fixture"].keys()))
def test_per_fixture_node_and_edge_counts(fid: str, validator: ShapeValidator):
    g = _fresh_graph_for(f"{fid}.json", validator)
    expected = GROUND_TRUTH["per_fixture"][fid]
    stats = g.stats()
    assert stats["nodes"] == expected["nodes_total"], (fid, stats)
    assert stats["edges"] == expected["edges_total"], (fid, stats)
    for label, count in expected["nodes_by_label"].items():
        assert stats["by_label"].get(label, 0) == count, (fid, label, stats)
    for label, count in expected["edges_by_label"].items():
        assert stats["edges_by_label"].get(label, 0) == count, (fid, label, stats)


def test_aggregate_stats_after_all_five(validator: ShapeValidator):
    g = _full_corpus_graph(validator)
    stats = g.stats()
    expected = GROUND_TRUTH["aggregate_after_all_five"]
    assert stats["nodes"] == expected["nodes_total"]
    assert stats["edges"] == expected["edges_total"]
    for label, count in expected["nodes_by_label"].items():
        assert stats["by_label"].get(label, 0) == count, label
    for label, count in expected["edges_by_label"].items():
        assert stats["edges_by_label"].get(label, 0) == count, label


# ── Idempotence ─────────────────────────────────────────────────────


def test_ingest_full_corpus_twice_is_idempotent(validator: ShapeValidator):
    g = PropertyGraph()
    p = CricsheetParser(g, validator)
    files = sorted(FIXTURES.glob("*.json"))
    for f in files:
        p.ingest_file(f)
    snapshot = copy.deepcopy(g.stats())
    pair_eid = ids.edge_id("TEAMMATES_WITH", "11111111", "22222222")
    pair_count_before = g.get_edge(pair_eid).props["match_count"]

    for f in files:
        p.ingest_file(f)
    assert g.stats() == snapshot
    assert g.get_edge(pair_eid).props["match_count"] == pair_count_before


# ── TEAMMATES_WITH semantics ────────────────────────────────────────


def test_teammates_match_count_increments_across_matches(validator: ShapeValidator):
    g = _full_corpus_graph(validator)
    spec = GROUND_TRUTH["aggregate_after_all_five"][
        "teammates_match_count_for_pak_core_pair"
    ]
    eid = ids.edge_id("TEAMMATES_WITH", spec["src"], spec["dst"])
    assert g.get_edge(eid).props["match_count"] == spec["match_count"]


def test_teammates_canonical_orientation(validator: ShapeValidator):
    g = _fresh_graph_for("1000001.json", validator)
    for e in g.edges_by_label("TEAMMATES_WITH"):
        assert e.src < e.dst, (e.src, e.dst)


# ── Per-match aggregation correctness ───────────────────────────────


def test_batted_in_runs_sum_correct(validator: ShapeValidator):
    g = _fresh_graph_for("1000001.json", validator)
    expected = GROUND_TRUTH["per_fixture"]["1000001"]["batter_runs"]
    for batter_id, runs in expected.items():
        eid = ids.edge_id("BATTED_IN", batter_id, "1000001")
        assert g.get_edge(eid).props["runs"] == runs, batter_id


def test_bowled_in_wickets_correct(validator: ShapeValidator):
    g = _fresh_graph_for("1000001.json", validator)
    expected = GROUND_TRUTH["per_fixture"]["1000001"]["bowler_wickets"]
    for bowler_id, wkts in expected.items():
        eid = ids.edge_id("BOWLED_IN", bowler_id, "1000001")
        assert g.get_edge(eid).props["wickets"] == wkts, bowler_id


def test_bowler_maiden_detected(validator: ShapeValidator):
    g = _fresh_graph_for("1000003.json", validator)
    eid = ids.edge_id("BOWLED_IN", "33333333", "1000003")
    edge = g.get_edge(eid)
    assert edge is not None
    assert edge.props["maidens"] == 1
    assert edge.props["runs_conceded"] == 0


# ── Topology ────────────────────────────────────────────────────────


def test_next_delivery_chain_intact_within_innings(validator: ShapeValidator):
    g = _fresh_graph_for("1000001.json", validator)
    iid = "1000001:1"
    deliveries = sorted(
        e.src
        for e in g.edges_by_label("IN_INNINGS")
        if e.dst == iid
    )
    chain = {e.src: e.dst for e in g.edges_by_label("NEXT_DELIVERY")}
    head = "1000001:1:0.1"
    walked = [head]
    cur = head
    while cur in chain:
        cur = chain[cur]
        walked.append(cur)
    assert sorted(walked) == sorted(deliveries)


def test_played_at_uses_unknown_when_venue_missing(validator: ShapeValidator):
    g = _fresh_graph_for("1000004.json", validator)
    venues = list(g.nodes_by_label("Venue"))
    assert len(venues) == 1
    assert venues[0].id == "unknown@unknown"
    assert venues[0].props["name"] == "unknown"


# ── Filter behaviour ────────────────────────────────────────────────


def test_format_filter_skips_non_matching(validator: ShapeValidator):
    g = PropertyGraph()
    p = CricsheetParser(g, validator, format_filter={"ODI"})
    report = p.ingest_directory(FIXTURES)
    # No ODI fixtures, so 5 skipped, 0 ingested.
    assert report.ingested == 0
    assert report.skipped_format == 5
    assert g.stats()["nodes"] == 0


def test_gender_filter_skips_non_matching(validator: ShapeValidator):
    g = PropertyGraph()
    p = CricsheetParser(g, validator, gender_filter="female")
    report = p.ingest_directory(FIXTURES)
    assert report.ingested == 0
    assert report.skipped_gender == 5


# ── Tournament + optional fields ────────────────────────────────────


def test_tournament_only_created_when_event_present(validator: ShapeValidator):
    no_event = _fresh_graph_for("1000001.json", validator)
    assert no_event.stats()["by_label"].get("Tournament", 0) == 0
    with_event = _fresh_graph_for("1000003.json", validator)
    assert with_event.stats()["by_label"]["Tournament"] == 1
    t_node = next(with_event.nodes_by_label("Tournament"))
    assert t_node.id == "asia-cup-2024"
    assert t_node.props["name"] == "Asia Cup 2024"


def test_super_over_flag_stored(validator: ShapeValidator):
    g = _fresh_graph_for("1000005.json", validator)
    innings = sorted(g.nodes_by_label("Innings"), key=lambda n: n.props["innings_idx"])
    assert innings[0].props.get("super_over") is not True
    assert innings[1].props["super_over"] is True


def test_declared_flag_stored(validator: ShapeValidator):
    g = _fresh_graph_for("1000002.json", validator)
    innings = sorted(g.nodes_by_label("Innings"), key=lambda n: n.props["innings_idx"])
    assert innings[0].props["declared"] is True
    assert "declared" not in innings[1].props


def test_captained_edge_uses_first_listed_player(validator: ShapeValidator):
    g = _fresh_graph_for("1000001.json", validator)
    # Babar Azam (PAK first-listed) and Joe Root (ENG first-listed).
    assert g.get_edge(ids.edge_id("CAPTAINED", "11111111", "1000001")) is not None
    assert g.get_edge(ids.edge_id("CAPTAINED", "44444444", "1000001")) is not None
    assert g.get_edge(ids.edge_id("CAPTAINED", "22222222", "1000001")) is None


def test_optional_dob_absent_does_not_raise(validator: ShapeValidator):
    # All fixtures omit dob — ingestion completes without ShapeViolationError.
    g = _full_corpus_graph(validator)
    assert g.stats()["nodes"] > 0
