"""Materialize the in-memory PropertyGraph into a normalized SQLite database.

One row per node label and per edge label. Foreign key indices on every
join column so SQLite's plan-cost estimator can pick reasonable joins.
The mirror is rebuilt from scratch on every invocation — there is no
incremental sync.

Run:
    python scripts/build_sqlite_mirror.py [--db data/cricket.db] [--data data/pakistan]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Iterable
from pathlib import Path

# Allow running as a plain script (python scripts/build_sqlite_mirror.py)
# in addition to `python -m scripts.build_sqlite_mirror` once it's a package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph.store import PropertyGraph
from ingestion.cricsheet_parser import CricsheetParser
from ingestion.validator import ShapeValidator

DEFAULT_DB = Path("data/cricket.db")
DEFAULT_DATA = Path("data/pakistan")


# Column projections for each node/edge label. Pulled here so the schema
# and INSERT loops stay in lock-step.
NODE_COLUMNS: dict[str, list[str]] = {
    "players": ["id", "name", "country", "dob", "batting_style", "bowling_style", "role"],
    "matches": [
        "id", "date", "format", "gender", "season",
        "venue_id", "city", "team_type", "balls_per_over",
        "outcome_winner", "outcome_method",
    ],
    "venues": ["id", "name", "city"],
    "teams": ["id", "name", "country_code", "type"],
    "innings": [
        "id", "match_id", "team_id", "innings_idx",
        "declared", "forfeited", "super_over", "target_runs", "target_overs",
    ],
    "deliveries": [
        "id", "innings_id", "over", "ball", "batter_id", "bowler_id",
        "runs_total", "runs_batter", "runs_extras",
        "wicket_kind", "player_out",
        "extras_wides", "extras_noballs", "extras_byes", "extras_legbyes", "extras_penalty",
    ],
    "tournaments": ["id", "name", "match_type", "season"],
}

EDGE_COLUMNS: dict[str, tuple[list[str], str, str]] = {
    # table_name -> (extra columns, src column, dst column)
    "played_for": (["first_match_date", "last_match_date"], "player_id", "team_id"),
    "batted_in": (["runs", "balls_faced", "fours", "sixes"], "player_id", "match_id"),
    "bowled_in": (["overs", "runs_conceded", "wickets", "maidens"], "player_id", "match_id"),
    "captained": ([], "player_id", "match_id"),
    "played_at": ([], "match_id", "venue_id"),
    "teammates_with": (["match_count"], "player_a_id", "player_b_id"),
    "in_innings": ([], "delivery_id", "innings_id"),
    "next_delivery": ([], "prev_id", "next_id"),
    "part_of_tournament": ([], "match_id", "tournament_id"),
}

NODE_LABEL_TO_TABLE = {
    "Player": "players",
    "Match": "matches",
    "Venue": "venues",
    "Team": "teams",
    "Innings": "innings",
    "Delivery": "deliveries",
    "Tournament": "tournaments",
}

EDGE_LABEL_TO_TABLE = {
    "PLAYED_FOR": "played_for",
    "BATTED_IN": "batted_in",
    "BOWLED_IN": "bowled_in",
    "CAPTAINED": "captained",
    "PLAYED_AT": "played_at",
    "TEAMMATES_WITH": "teammates_with",
    "IN_INNINGS": "in_innings",
    "NEXT_DELIVERY": "next_delivery",
    "PART_OF_TOURNAMENT": "part_of_tournament",
}


def _column_type(col: str) -> str:
    if col in {
        "innings_idx", "over", "ball",
        "balls_per_over", "target_runs", "target_overs",
        "runs_total", "runs_batter", "runs_extras",
        "extras_wides", "extras_noballs", "extras_byes", "extras_legbyes", "extras_penalty",
        "runs", "balls_faced", "fours", "sixes",
        "runs_conceded", "wickets", "maidens", "match_count",
    }:
        return "INTEGER"
    if col in {"declared", "forfeited", "super_over"}:
        return "INTEGER"  # SQLite stores booleans as 0/1
    if col == "overs":
        return "REAL"
    return "TEXT"


def _create_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for table, cols in NODE_COLUMNS.items():
        col_defs = ", ".join(f"{c} {_column_type(c)}" for c in cols)
        pk = "PRIMARY KEY" if "id" in cols else ""
        col_defs = col_defs.replace("id TEXT", f"id TEXT {pk}", 1)
        cur.execute(f"CREATE TABLE {table} ({col_defs})")
    for table, (extra, src_col, dst_col) in EDGE_COLUMNS.items():
        all_cols = [src_col, dst_col, *extra]
        col_defs = ", ".join(f"{c} {_column_type(c)}" for c in all_cols)
        cur.execute(f"CREATE TABLE {table} ({col_defs})")
        cur.execute(f"CREATE INDEX idx_{table}_{src_col} ON {table}({src_col})")
        cur.execute(f"CREATE INDEX idx_{table}_{dst_col} ON {table}({dst_col})")
    conn.commit()


def _insert_nodes(conn: sqlite3.Connection, graph: PropertyGraph) -> None:
    cur = conn.cursor()
    for label, table in NODE_LABEL_TO_TABLE.items():
        cols = NODE_COLUMNS[table]
        placeholders = ", ".join("?" * len(cols))
        col_list = ", ".join(cols)
        rows = []
        for n in graph.nodes_by_label(label):
            rows.append(tuple(n.props.get(c) for c in cols))
        if rows:
            cur.executemany(
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", rows
            )
    conn.commit()


def _insert_edges(conn: sqlite3.Connection, graph: PropertyGraph) -> None:
    cur = conn.cursor()
    for label, table in EDGE_LABEL_TO_TABLE.items():
        extra, src_col, dst_col = EDGE_COLUMNS[table]
        cols = [src_col, dst_col, *extra]
        placeholders = ", ".join("?" * len(cols))
        col_list = ", ".join(cols)
        rows = []
        for e in graph.edges_by_label(label):
            base = (e.src, e.dst)
            extras = tuple(e.props.get(c) for c in extra)
            rows.append(base + extras)
        if rows:
            cur.executemany(
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", rows
            )
    conn.commit()


def build_mirror(graph: PropertyGraph, db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    _create_schema(conn)
    _insert_nodes(conn, graph)
    _insert_edges(conn, graph)
    return conn


def _load_graph(data_dir: Path, shapes: Path) -> PropertyGraph:
    g = PropertyGraph()
    p = CricsheetParser(g, ShapeValidator(shapes))
    for f in sorted(data_dir.glob("*.json")):
        try:
            p.ingest_file(f)
        except Exception as exc:
            print(f"[warn] {f}: {exc}", file=sys.stderr)
    return g


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--shapes", type=Path, default=Path("ontology/shapes.yaml"))
    args = ap.parse_args(list(argv) if argv is not None else None)
    print(f"[load] ingesting {args.data}", file=sys.stderr)
    graph = _load_graph(args.data, args.shapes)
    print(f"[load] graph stats: {graph.stats()}", file=sys.stderr)
    print(f"[mirror] writing {args.db}", file=sys.stderr)
    conn = build_mirror(graph, args.db)
    cur = conn.cursor()
    counts = {}
    for table in NODE_LABEL_TO_TABLE.values():
        counts[table] = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    for table in EDGE_LABEL_TO_TABLE.values():
        counts[table] = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    print(f"[mirror] row counts: {counts}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
