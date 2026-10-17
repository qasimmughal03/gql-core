"""Deterministic ID derivation for cricket-kg nodes and edges.

Pure functions; no I/O. All formulae are deterministic so that re-ingestion
of the same cricsheet file yields byte-identical IDs and the graph store's
idempotent add_node / add_edge merges rather than duplicates.
"""

from __future__ import annotations

import re
from pathlib import Path

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_HEX_RE = re.compile(r"^[a-f0-9]{8}$")

# Mapping of cricsheet team names to ISO-style country codes.
# Cricsheet uses the full team name in info.teams; the registry doesn't
# carry a country code, so we hand-map the common internationals.
_COUNTRY_CODES: dict[str, str] = {
    "Pakistan": "PAK",
    "India": "IND",
    "Australia": "AUS",
    "England": "ENG",
    "South Africa": "RSA",
    "New Zealand": "NZL",
    "Sri Lanka": "SRI",
    "West Indies": "WIN",
    "Bangladesh": "BAN",
    "Zimbabwe": "ZIM",
    "Afghanistan": "AFG",
    "Ireland": "IRE",
    "Scotland": "SCO",
    "Netherlands": "NED",
    "Nepal": "NEP",
    "United Arab Emirates": "UAE",
    "Oman": "OMA",
    "Hong Kong": "HK",
    "Kenya": "KEN",
    "Namibia": "NAM",
    "Papua New Guinea": "PNG",
    "United States of America": "USA",
    "Canada": "CAN",
}


def slug(s: str | None) -> str:
    """Lowercase, collapse non-alnum to '-', strip edges. Empty/None → 'unknown'."""
    if s is None:
        return "unknown"
    out = _SLUG_RE.sub("-", s.strip().lower()).strip("-")
    return out or "unknown"


def player_id(registry_hex: str | None, name: str) -> str:
    """Cricsheet 8-char hex from info.registry.people; fallback slug(name)."""
    if registry_hex and _HEX_RE.match(registry_hex):
        return registry_hex
    return slug(name)


def match_id(filename: str | Path) -> str:
    """Cricsheet ships stable numeric IDs as filenames (e.g. 1234567.json)."""
    return Path(filename).stem


def venue_id(venue: str | None, city: str | None) -> str:
    return f"{slug(venue)}@{slug(city)}"


def team_id(team_name: str, country_code: str | None = None) -> str:
    if country_code:
        return country_code.upper()
    cc = _COUNTRY_CODES.get(team_name)
    if cc:
        return cc
    return slug(team_name)


def innings_id(match_id_value: str, innings_idx: int) -> str:
    return f"{match_id_value}:{innings_idx}"


def delivery_id(
    match_id_value: str, innings_idx: int, over: int, ball_idx: int
) -> str:
    return f"{match_id_value}:{innings_idx}:{over}.{ball_idx}"


def tournament_id(event_name: str | None) -> str | None:
    """None signals the caller to skip Tournament node + edge."""
    if not event_name:
        return None
    return slug(event_name)


def edge_id(label: str, src: str, dst: str, disambiguator: str | None = None) -> str:
    base = f"{label}:{src}:{dst}"
    return f"{base}:{disambiguator}" if disambiguator else base
