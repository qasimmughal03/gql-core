from __future__ import annotations

from pathlib import Path

import pytest

from ingestion.validator import ShapeValidator, ShapeViolationError

SHAPES = Path(__file__).resolve().parent.parent / "ontology" / "shapes.yaml"


@pytest.fixture(scope="module")
def validator() -> ShapeValidator:
    return ShapeValidator(SHAPES)


# ── Node validation ─────────────────────────────────────────────────


def test_required_field_missing_raises(validator: ShapeValidator):
    with pytest.raises(ShapeViolationError) as exc:
        validator.validate_node("Player", {"id": "fd423c3b", "country": "PAK"})
    assert exc.value.field == "name"
    assert exc.value.reason == "required"


def test_type_mismatch_raises(validator: ShapeValidator):
    with pytest.raises(ShapeViolationError) as exc:
        validator.validate_node(
            "Match",
            {
                "id": "12345",
                "date": "2022-12-01",
                "format": "Test",
                "gender": "male",
                "season": "2022/23",
                "balls_per_over": "six",
            },
        )
    assert exc.value.field == "balls_per_over"
    assert exc.value.reason == "type"


def test_enum_violation_raises(validator: ShapeValidator):
    with pytest.raises(ShapeViolationError) as exc:
        validator.validate_node(
            "Match",
            {
                "id": "12345",
                "date": "2022-12-01",
                "format": "Hundred",
                "gender": "male",
                "season": "2022/23",
            },
        )
    assert exc.value.field == "format"
    assert exc.value.reason == "enum"


def test_pattern_violation_raises(validator: ShapeValidator):
    with pytest.raises(ShapeViolationError) as exc:
        validator.validate_node(
            "Player",
            {"id": "BAD!ID", "name": "x", "country": "PAK"},
        )
    assert exc.value.field == "id"
    assert exc.value.reason == "pattern"


def test_min_violation_raises(validator: ShapeValidator):
    with pytest.raises(ShapeViolationError) as exc:
        validator.validate_node(
            "Match",
            {
                "id": "12345",
                "date": "2022-12-01",
                "format": "Test",
                "gender": "male",
                "season": "2022/23",
                "balls_per_over": 0,
            },
        )
    assert exc.value.field == "balls_per_over"
    assert exc.value.reason == "min"


def test_max_violation_raises(validator: ShapeValidator):
    with pytest.raises(ShapeViolationError) as exc:
        validator.validate_node(
            "Match",
            {
                "id": "12345",
                "date": "2022-12-01",
                "format": "Test",
                "gender": "male",
                "season": "2022/23",
                "balls_per_over": 99,
            },
        )
    assert exc.value.field == "balls_per_over"
    assert exc.value.reason == "max"


def test_valid_player_passes_silently(validator: ShapeValidator):
    validator.validate_node(
        "Player",
        {
            "id": "fd423c3b",
            "name": "Babar Azam",
            "country": "PAK",
            "batting_style": "right-hand bat",
        },
    )


def test_valid_match_with_optional_fields_passes(validator: ShapeValidator):
    validator.validate_node(
        "Match",
        {
            "id": "12345",
            "date": "2022-12-01",
            "format": "Test",
            "gender": "male",
            "season": "2022/23",
            "venue_id": "national-stadium@karachi",
            "city": "Karachi",
            "balls_per_over": 6,
        },
    )


def test_optional_field_absent_passes(validator: ShapeValidator):
    validator.validate_node(
        "Player",
        {"id": "fd423c3b", "name": "X", "country": "PAK"},
    )


def test_unknown_node_label_raises(validator: ShapeValidator):
    with pytest.raises(ShapeViolationError):
        validator.validate_node("Phantom", {"id": "x"})


def test_bool_not_treated_as_int(validator: ShapeValidator):
    with pytest.raises(ShapeViolationError) as exc:
        validator.validate_node(
            "Match",
            {
                "id": "12345",
                "date": "2022-12-01",
                "format": "Test",
                "gender": "male",
                "season": "2022/23",
                "balls_per_over": True,
            },
        )
    assert exc.value.field == "balls_per_over"
    assert exc.value.reason == "type"


# ── Edge validation ─────────────────────────────────────────────────


def test_edge_endpoint_label_mismatch_raises(validator: ShapeValidator):
    with pytest.raises(ShapeViolationError) as exc:
        validator.validate_edge("BATTED_IN", "Match", "Player")
    assert exc.value.reason == "endpoint_label"


def test_edge_endpoint_label_correct_passes(validator: ShapeValidator):
    validator.validate_edge("BATTED_IN", "Player", "Match", {"runs": 100})


def test_edge_property_type_mismatch_raises(validator: ShapeValidator):
    with pytest.raises(ShapeViolationError) as exc:
        validator.validate_edge(
            "BATTED_IN", "Player", "Match", {"runs": "many"}
        )
    assert exc.value.field == "runs"
    assert exc.value.reason == "type"


def test_unknown_edge_label_raises(validator: ShapeValidator):
    with pytest.raises(ShapeViolationError):
        validator.validate_edge("PHANTOM", "Player", "Match")


def test_delivery_wicket_kind_enum_passes(validator: ShapeValidator):
    validator.validate_node(
        "Delivery",
        {
            "id": "1234567:1:0.1",
            "innings_id": "1234567:1",
            "over": 0,
            "ball": 1,
            "batter_id": "fd423c3b",
            "bowler_id": "abcdef01",
            "runs_total": 0,
            "wicket_kind": "caught and bowled",
            "player_out": "fd423c3b",
        },
    )


def test_delivery_wicket_kind_unknown_enum_raises(validator: ShapeValidator):
    with pytest.raises(ShapeViolationError) as exc:
        validator.validate_node(
            "Delivery",
            {
                "id": "1234567:1:0.1",
                "innings_id": "1234567:1",
                "over": 0,
                "ball": 1,
                "batter_id": "fd423c3b",
                "bowler_id": "abcdef01",
                "runs_total": 0,
                "wicket_kind": "outsmarted",
            },
        )
    assert exc.value.field == "wicket_kind"
