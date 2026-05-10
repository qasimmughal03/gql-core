from __future__ import annotations

from ingestion.ids import (
    delivery_id,
    edge_id,
    innings_id,
    match_id,
    player_id,
    slug,
    team_id,
    tournament_id,
    venue_id,
)


def test_slug_basic():
    assert slug("National Stadium") == "national-stadium"
    assert slug("  Foo  Bar  ") == "foo-bar"
    assert slug("Babar  Azam!") == "babar-azam"


def test_slug_handles_none_and_empty():
    assert slug(None) == "unknown"
    assert slug("") == "unknown"
    assert slug("   ") == "unknown"


def test_player_id_prefers_registry_hex():
    assert player_id("fd423c3b", "Babar Azam") == "fd423c3b"


def test_player_id_falls_back_when_hex_invalid():
    assert player_id(None, "Babar Azam") == "babar-azam"
    assert player_id("not-hex", "Babar Azam") == "babar-azam"
    assert player_id("FD423C3B", "Babar Azam") == "babar-azam"  # uppercase rejected


def test_match_id_uses_filename_stem():
    assert match_id("/data/pakistan/1234567.json") == "1234567"
    assert match_id("rel/path/9999.json") == "9999"


def test_venue_id_combines_components():
    assert venue_id("National Stadium", "Karachi") == "national-stadium@karachi"
    assert venue_id(None, "Karachi") == "unknown@karachi"
    assert venue_id("National Stadium", None) == "national-stadium@unknown"
    assert venue_id(None, None) == "unknown@unknown"


def test_team_id_uses_country_map():
    assert team_id("Pakistan") == "PAK"
    assert team_id("England") == "ENG"
    assert team_id("Lahore Qalandars") == "lahore-qalandars"


def test_team_id_explicit_country_code_wins():
    assert team_id("Pakistan", "pak") == "PAK"


def test_innings_and_delivery_ids():
    assert innings_id("1234567", 1) == "1234567:1"
    assert delivery_id("1234567", 2, 5, 3) == "1234567:2:5.3"


def test_tournament_id_returns_none_when_event_absent():
    assert tournament_id(None) is None
    assert tournament_id("") is None
    assert tournament_id("Asia Cup 2022") == "asia-cup-2022"


def test_edge_id_with_and_without_disambiguator():
    assert edge_id("BATTED_IN", "fd423c3b", "1234567") == "BATTED_IN:fd423c3b:1234567"
    assert (
        edge_id("BATTED_IN", "fd423c3b", "1234567", "2")
        == "BATTED_IN:fd423c3b:1234567:2"
    )
