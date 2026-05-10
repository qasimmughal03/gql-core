"""Cricsheet JSON ingestion.

Parses one match at a time into validated PropertyGraph insertions:

  Match            ─ from info{teams,date,format,gender,season,venue,city,...}
  Venue            ─ from info{venue,city}
  Team             ─ from info.teams
  Tournament       ─ from info.event (optional)
  Player           ─ from info.players + info.registry.people
  Innings          ─ from innings[i]
  Delivery         ─ from innings[i].overs[j].deliveries[k]

  PLAYED_FOR       ─ Player → Team (per match)
  CAPTAINED        ─ Player → Match (heuristic: first-listed player per team
                     unless info.officials lists captains explicitly)
  PLAYED_AT        ─ Match → Venue
  PART_OF_TOURNAMENT ─ Match → Tournament (only when info.event present)
  IN_INNINGS       ─ Delivery → Innings
  NEXT_DELIVERY    ─ Delivery → Delivery (intra-innings, legal-ball order)
  BATTED_IN        ─ Player → Match (per-match aggregation)
  BOWLED_IN        ─ Player → Match (per-match aggregation)
  TEAMMATES_WITH   ─ Player ↔ Player (canonical src=min(id), dst=max(id);
                     match_count incremented; idempotent via graph.seen_match_ids)

Run as a module:
    python -m ingestion.cricsheet_parser data/pakistan
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

from graph.store import Edge, Node, PropertyGraph
from ingestion import ids
from ingestion.validator import ShapeValidator, ShapeViolationError

ALLOWED_FORMATS = {"Test", "ODI", "T20", "IT20", "ODM", "MDM"}

# Wickets credited to the bowler. Cricsheet ships the kind verbatim;
# run-outs and retirements are not the bowler's wickets per ICC rules.
_BOWLER_CREDITED_WICKETS = {
    "bowled",
    "caught",
    "lbw",
    "stumped",
    "hit wicket",
    "caught and bowled",
}


@dataclass
class IngestReport:
    ingested: int = 0
    skipped_format: int = 0
    skipped_gender: int = 0
    errors: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ingested": self.ingested,
            "skipped_format": self.skipped_format,
            "skipped_gender": self.skipped_gender,
            "errors": list(self.errors),
        }


class CricsheetParser:
    def __init__(
        self,
        graph: PropertyGraph,
        validator: ShapeValidator,
        *,
        format_filter: set[str] | None = None,
        gender_filter: str | None = None,
    ) -> None:
        self.graph = graph
        self.validator = validator
        self.format_filter = format_filter
        self.gender_filter = gender_filter

    # ── Public API ────────────────────────────────────────────────

    def ingest_directory(self, dirpath: str | Path) -> IngestReport:
        report = IngestReport()
        for path in sorted(Path(dirpath).glob("*.json")):
            try:
                if not self.ingest_file(path, report=report):
                    continue
                report.ingested += 1
            except ShapeViolationError as exc:
                report.errors.append(
                    {
                        "file": str(path),
                        "label": exc.label,
                        "field": exc.field,
                        "reason": exc.reason,
                        "value": str(exc.value)[:200],
                    }
                )
        return report

    def ingest_file(self, filepath: str | Path, *, report: IngestReport | None = None) -> bool:
        path = Path(filepath)
        with path.open() as f:
            data = json.load(f)
        info = data.get("info") or {}

        fmt = info.get("match_type")
        if self.format_filter is not None and fmt not in self.format_filter:
            if report is not None:
                report.skipped_format += 1
            return False
        if self.gender_filter is not None and info.get("gender") != self.gender_filter:
            if report is not None:
                report.skipped_gender += 1
            return False

        mid = ids.match_id(path)
        name_to_pid = self._parse_info(mid, info)
        self._parse_innings(mid, data.get("innings") or [], info, name_to_pid)
        self._materialize_teammates(mid, info, name_to_pid)
        return True

    # ── Internals ─────────────────────────────────────────────────

    def _parse_info(self, mid: str, info: dict) -> dict[str, str]:
        # ---------- Match node ----------
        dates = info.get("dates") or []
        match_props: dict[str, Any] = {
            "id": mid,
            "date": dates[0] if dates else "unknown",
            "format": info.get("match_type", "unknown"),
            "gender": info.get("gender", "unknown"),
            "season": str(info.get("season", "unknown")),
        }
        if (city := info.get("city")) is not None:
            match_props["city"] = city
        if (tt := info.get("team_type")) is not None:
            match_props["team_type"] = tt
        if (bpo := info.get("balls_per_over")) is not None:
            match_props["balls_per_over"] = bpo
        outcome = info.get("outcome") or {}
        if (winner := outcome.get("winner")) is not None:
            match_props["outcome_winner"] = winner
        if (method := outcome.get("method")) is not None:
            match_props["outcome_method"] = method

        # ---------- Venue ----------
        venue_name = info.get("venue")
        vid = ids.venue_id(venue_name, info.get("city"))
        match_props["venue_id"] = vid
        venue_props: dict[str, Any] = {"id": vid, "name": venue_name or "unknown"}
        if (city := info.get("city")) is not None:
            venue_props["city"] = city
        self._add_node("Venue", venue_props)
        self._add_node("Match", match_props)
        self._add_edge(
            "PLAYED_AT", "Match", "Venue", mid, vid, {}
        )

        # ---------- Tournament ----------
        event = info.get("event") or {}
        event_name = event.get("name") if isinstance(event, dict) else None
        tid = ids.tournament_id(event_name)
        if tid is not None:
            t_props: dict[str, Any] = {"id": tid, "name": event_name}
            if fmt := info.get("match_type"):
                t_props["match_type"] = fmt
            if season := info.get("season"):
                t_props["season"] = str(season)
            self._add_node("Tournament", t_props)
            self._add_edge(
                "PART_OF_TOURNAMENT", "Match", "Tournament", mid, tid, {}
            )

        # ---------- Teams ----------
        teams = info.get("teams") or []
        team_ids: dict[str, str] = {}
        for team_name in teams:
            t_id = ids.team_id(team_name)
            team_ids[team_name] = t_id
            team_props: dict[str, Any] = {"id": t_id, "name": team_name}
            cc = ids._COUNTRY_CODES.get(team_name)
            if cc:
                team_props["country_code"] = cc
                team_props["type"] = "international"
            else:
                team_props["type"] = info.get("team_type") or "club"
            self._add_node("Team", team_props)

        # ---------- Players ----------
        registry = (info.get("registry") or {}).get("people") or {}
        players_by_team: dict[str, list[str]] = info.get("players") or {}
        name_to_pid: dict[str, str] = {}
        for team_name, names in players_by_team.items():
            t_id = team_ids.get(team_name) or ids.team_id(team_name)
            for name in names:
                pid = ids.player_id(registry.get(name), name)
                name_to_pid[name] = pid
                # Player country = team if international, else 'club'.
                country = ids._COUNTRY_CODES.get(team_name) or team_name
                player_props: dict[str, Any] = {
                    "id": pid,
                    "name": name,
                    "country": country,
                }
                self._add_node("Player", player_props)
                self._add_edge(
                    "PLAYED_FOR",
                    "Player",
                    "Team",
                    pid,
                    t_id,
                    {
                        "first_match_date": match_props["date"],
                        "last_match_date": match_props["date"],
                    },
                )

        # ---------- Captains ----------
        # Cricsheet has no canonical captain field. Heuristic: the first
        # player listed for each team is their captain for that match.
        # Documented limitation; can be refined by checking other-format files.
        for team_name, names in players_by_team.items():
            if not names:
                continue
            captain_name = names[0]
            cap_pid = name_to_pid.get(captain_name)
            if cap_pid is None:
                continue
            self._add_edge("CAPTAINED", "Player", "Match", cap_pid, mid, {})

        return name_to_pid

    def _parse_innings(
        self,
        mid: str,
        innings_list: list,
        info: dict,
        name_to_pid: dict[str, str],
    ) -> None:
        bpo = info.get("balls_per_over") or 6
        # Aggregation buckets keyed by (player_id, match_id).
        batter_stats: dict[str, dict[str, int]] = {}
        bowler_stats: dict[str, dict[str, Any]] = {}

        for innings_idx, innings in enumerate(innings_list, start=1):
            team_name = innings.get("team", "unknown")
            t_id = ids.team_id(team_name)
            iid = ids.innings_id(mid, innings_idx)
            innings_props: dict[str, Any] = {
                "id": iid,
                "match_id": mid,
                "team_id": t_id,
                "innings_idx": innings_idx,
            }
            for opt in ("declared", "forfeited", "super_over"):
                if opt in innings:
                    innings_props[opt] = bool(innings[opt])
            target = innings.get("target")
            if isinstance(target, dict):
                if "runs" in target:
                    innings_props["target_runs"] = int(target["runs"])
                if "overs" in target:
                    innings_props["target_overs"] = int(target["overs"])
            self._add_node("Innings", innings_props)

            prev_did: str | None = None
            # Per-over running tally for maiden detection.
            for over_obj in innings.get("overs") or []:
                over_no = int(over_obj.get("over", 0))
                deliveries = over_obj.get("deliveries") or []
                over_legal_balls = 0
                over_runs_to_bowler = 0
                over_bowler: str | None = None
                for ball_idx, d in enumerate(deliveries, start=1):
                    did = ids.delivery_id(mid, innings_idx, over_no, ball_idx)
                    runs = d.get("runs") or {}
                    extras = d.get("extras") or {}
                    runs_total = int(runs.get("total", 0))
                    runs_batter = int(runs.get("batter", 0))
                    runs_extras = int(runs.get("extras", 0))
                    batter_name = d.get("batter")
                    bowler_name = d.get("bowler")
                    batter_pid = name_to_pid.get(batter_name) or ids.player_id(
                        None, batter_name or "unknown"
                    )
                    bowler_pid = name_to_pid.get(bowler_name) or ids.player_id(
                        None, bowler_name or "unknown"
                    )
                    over_bowler = bowler_pid

                    delivery_props: dict[str, Any] = {
                        "id": did,
                        "innings_id": iid,
                        "over": over_no,
                        "ball": ball_idx,
                        "batter_id": batter_pid,
                        "bowler_id": bowler_pid,
                        "runs_total": runs_total,
                        "runs_batter": runs_batter,
                        "runs_extras": runs_extras,
                    }
                    for ek, prop_name in (
                        ("wides", "extras_wides"),
                        ("noballs", "extras_noballs"),
                        ("byes", "extras_byes"),
                        ("legbyes", "extras_legbyes"),
                        ("penalty", "extras_penalty"),
                    ):
                        if ek in extras:
                            delivery_props[prop_name] = int(extras[ek])

                    wickets = d.get("wickets") or []
                    if wickets:
                        # Take the first wicket as primary (rare to have >1).
                        w = wickets[0]
                        kind = w.get("kind")
                        if kind:
                            delivery_props["wicket_kind"] = kind
                        if (po := w.get("player_out")) is not None:
                            delivery_props["player_out"] = po
                        fielders = w.get("fielders") or []
                        if fielders:
                            delivery_props["fielders"] = [
                                f.get("name") for f in fielders if isinstance(f, dict)
                            ]

                    self._add_node("Delivery", delivery_props)
                    self._add_edge("IN_INNINGS", "Delivery", "Innings", did, iid, {})
                    if prev_did is not None:
                        self._add_edge(
                            "NEXT_DELIVERY", "Delivery", "Delivery", prev_did, did, {}
                        )
                    prev_did = did

                    is_legal = "wides" not in extras and "noballs" not in extras
                    if is_legal:
                        over_legal_balls += 1

                    # Batter aggregation. Wides: not a ball faced AND not credited.
                    bs = batter_stats.setdefault(
                        batter_pid,
                        {"runs": 0, "balls_faced": 0, "fours": 0, "sixes": 0},
                    )
                    if "wides" not in extras:
                        bs["balls_faced"] += 1
                        bs["runs"] += runs_batter
                        if runs_batter == 4 and not runs.get("non_boundary"):
                            bs["fours"] += 1
                        elif runs_batter == 6:
                            bs["sixes"] += 1

                    # Bowler aggregation.
                    runs_to_bowler = runs_batter + int(extras.get("wides", 0)) + int(
                        extras.get("noballs", 0)
                    )
                    over_runs_to_bowler += runs_to_bowler
                    bw = bowler_stats.setdefault(
                        bowler_pid,
                        {
                            "legal_balls": 0,
                            "runs_conceded": 0,
                            "wickets": 0,
                            "maidens": 0,
                        },
                    )
                    if is_legal:
                        bw["legal_balls"] += 1
                    bw["runs_conceded"] += runs_to_bowler
                    if wickets:
                        for w in wickets:
                            if w.get("kind") in _BOWLER_CREDITED_WICKETS:
                                bw["wickets"] += 1

                # Maiden detection: legal-ball-complete over with zero runs charged.
                if (
                    over_bowler is not None
                    and over_legal_balls >= bpo
                    and over_runs_to_bowler == 0
                ):
                    bowler_stats[over_bowler]["maidens"] += 1

        # Flush BATTED_IN / BOWLED_IN once per match.
        for pid, bs in batter_stats.items():
            self._add_edge(
                "BATTED_IN",
                "Player",
                "Match",
                pid,
                mid,
                {
                    "runs": bs["runs"],
                    "balls_faced": bs["balls_faced"],
                    "fours": bs["fours"],
                    "sixes": bs["sixes"],
                },
            )
        for pid, bw in bowler_stats.items():
            overs_dec = bw["legal_balls"] // bpo + (bw["legal_balls"] % bpo) / 10
            self._add_edge(
                "BOWLED_IN",
                "Player",
                "Match",
                pid,
                mid,
                {
                    "overs": float(overs_dec),
                    "runs_conceded": bw["runs_conceded"],
                    "wickets": bw["wickets"],
                    "maidens": bw["maidens"],
                },
            )

    def _materialize_teammates(
        self, mid: str, info: dict, name_to_pid: dict[str, str]
    ) -> None:
        if mid in self.graph.seen_match_ids:
            return
        players_by_team: dict[str, list[str]] = info.get("players") or {}
        for names in players_by_team.values():
            pids = sorted(
                {name_to_pid.get(n) for n in names if name_to_pid.get(n) is not None}
            )
            for a, b in combinations(pids, 2):
                src, dst = (a, b) if a < b else (b, a)
                eid = ids.edge_id("TEAMMATES_WITH", src, dst)
                existing = self.graph.get_edge(eid)
                new_count = (existing.props.get("match_count", 0) + 1) if existing else 1
                self.graph.add_edge(
                    Edge(
                        id=eid,
                        label="TEAMMATES_WITH",
                        src=src,
                        dst=dst,
                        props={"match_count": new_count},
                    )
                )
        self.graph.seen_match_ids.add(mid)

    # ── Helpers ───────────────────────────────────────────────────

    def _add_node(self, label: str, props: dict[str, Any]) -> None:
        self.validator.validate_node(label, props)
        self.graph.add_node(Node(id=props["id"], label=label, props=dict(props)))

    def _add_edge(
        self,
        label: str,
        src_label: str,
        dst_label: str,
        src: str,
        dst: str,
        props: dict[str, Any],
    ) -> None:
        self.validator.validate_edge(label, src_label, dst_label, props)
        eid = ids.edge_id(label, src, dst)
        self.graph.add_edge(
            Edge(id=eid, label=label, src=src, dst=dst, props=dict(props))
        )


# ── CLI ───────────────────────────────────────────────────────────


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ingest cricsheet JSON files into a PropertyGraph.")
    ap.add_argument("dirpath", type=Path, help="Directory containing *.json files")
    ap.add_argument("--shapes", type=Path, default=Path("ontology/shapes.yaml"))
    ap.add_argument("--gender", default="male", help="Filter by gender (default: male; '' to disable)")
    ap.add_argument(
        "--formats",
        default="Test,ODI,T20,IT20",
        help="Comma-separated formats to ingest (default: Test,ODI,T20,IT20)",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    graph = PropertyGraph()
    validator = ShapeValidator(args.shapes)
    fmt_filter = {f.strip() for f in args.formats.split(",") if f.strip()} if args.formats else None
    gender = args.gender or None
    parser = CricsheetParser(
        graph, validator, format_filter=fmt_filter, gender_filter=gender
    )
    report = parser.ingest_directory(args.dirpath)
    stats = graph.stats()
    print(json.dumps({"report": report.as_dict(), "stats": stats}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
