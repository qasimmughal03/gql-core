"""Run all benchmarks across every domain and produce a unified accuracy report.

Usage:
    python examples/run_all_benchmarks.py [--iters 30] [--out results.json]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from graph.store import PropertyGraph
from ingestion.cricsheet_parser import CricsheetParser
from ingestion.validator import ShapeValidator
from gql_core.benchmark import run_benchmark as run_bm
from gql_core.graph import PropertyGraph as GqlGraph
from gql_core.ingester import GraphIngester
from gql_core.validator import ShapeValidator as GqlValidator
from gql_core.mirror import build_mirror


BENCHMARKS = [
    {
        "domain": "cricket",
        "name": "Cricket Direct Queries (Q1-Q5)",
        "shapes": "examples/cricket/shapes.yaml",
        "data_dir": "tests/fixtures",
        "suite": None,  # custom
        "use_cricsheet": True,
        "db": "examples/cricket/cricket.db",
    },
    {
        "domain": "movies",
        "name": "Movie Knowledge Graph",
        "shapes": "examples/movies/shapes.yaml",
        "data_file": "examples/movies/graph.json",
        "suite": "examples/movies/suite.yaml",
        "db": "examples/movies/movies.db",
    },
    {
        "domain": "starwars",
        "name": "Star Wars Knowledge Graph",
        "shapes": "examples/starwars/shapes.yaml",
        "data_file": "examples/starwars/graph.json",
        "suite": "examples/starwars/suite.yaml",
        "db": "examples/starwars/sw.db",
    },
    {
        "domain": "social",
        "name": "Generic Social Graph",
        "shapes": "tests/fixtures/generic/shapes.yaml",
        "data_file": "tests/fixtures/generic/social_graph.json",
        "suite": "tests/fixtures/generic/suite.yaml",
        "db": "tests/fixtures/generic/social.db",
    },
]

# Cricket direct queries (Q1-Q5) from the original benchmark
CRICKET_QUERIES = [
    {
        "name": "Q1_career_runs",
        "query_class": "aggregation",
        "gql": "MATCH (p:Player)-[r:BATTED_IN]->(m:Match) RETURN p.name AS player, SUM(r.runs) AS career_runs ORDER BY career_runs DESC LIMIT 10",
        "sql": "SELECT pl.name AS player, SUM(b.runs) AS career_runs FROM batted_in b JOIN players pl ON pl.id = b.player_id GROUP BY pl.id, pl.name ORDER BY career_runs DESC, pl.name ASC LIMIT 10",
        "key_columns": ["player", "career_runs"],
    },
    {
        "name": "Q2_best_bowling_at_karachi",
        "query_class": "multi_hop",
        "gql": 'MATCH (p:Player)-[r:BOWLED_IN]->(m:Match)-[:PLAYED_AT]->(v:Venue) WHERE v.city = "Karachi" RETURN p.name AS bowler, MAX(r.wickets) AS best_haul ORDER BY best_haul DESC, bowler ASC LIMIT 5',
        "sql": "SELECT pl.name AS bowler, MAX(b.wickets) AS best_haul FROM bowled_in b JOIN players pl ON pl.id = b.player_id JOIN matches m ON m.id = b.match_id JOIN venues v ON v.id = m.venue_id WHERE v.city = 'Karachi' GROUP BY pl.id, pl.name ORDER BY best_haul DESC, pl.name ASC LIMIT 5",
        "key_columns": ["bowler", "best_haul"],
    },
    {
        "name": "Q3_pakistan_captain_wins",
        "query_class": "simple_lookup",
        "gql": 'MATCH (p:Player)-[:CAPTAINED]->(m:Match) WHERE m.outcome_winner = "Pakistan" AND p.country = "PAK" RETURN p.name AS captain, COUNT(m) AS wins ORDER BY wins DESC LIMIT 5',
        "sql": "SELECT pl.name AS captain, COUNT(*) AS wins FROM captained c JOIN players pl ON pl.id = c.player_id JOIN matches m ON m.id = c.match_id WHERE m.outcome_winner = 'Pakistan' AND pl.country = 'PAK' GROUP BY pl.id, pl.name ORDER BY wins DESC, pl.name ASC LIMIT 5",
        "key_columns": ["captain", "wins"],
    },
    {
        "name": "Q4_babar_partners",
        "query_class": "undirected",
        "gql": 'MATCH (p1:Player)-[t:TEAMMATES_WITH]-(p2:Player) WHERE p1.name = "Babar Azam" RETURN p2.name AS partner, t.match_count AS shared ORDER BY shared DESC LIMIT 10',
        "sql": "SELECT pl2.name AS partner, t.match_count AS shared FROM teammates_with t JOIN players pl1 ON pl1.id = t.player_a_id JOIN players pl2 ON pl2.id = t.player_b_id WHERE pl1.name = 'Babar Azam' UNION ALL SELECT pl1.name AS partner, t.match_count AS shared FROM teammates_with t JOIN players pl1 ON pl1.id = t.player_a_id JOIN players pl2 ON pl2.id = t.player_b_id WHERE pl2.name = 'Babar Azam' ORDER BY shared DESC, partner ASC LIMIT 10",
        "key_columns": ["partner", "shared"],
    },
    {
        "name": "Q5_rpq_next_delivery",
        "query_class": "rpq",
        "gql": 'MATCH (d:Delivery)-[:NEXT_DELIVERY*1..3]->(d2:Delivery) WHERE d.id = "{start_id}" RETURN d.id AS start, COUNT(d2) AS reachable',
        "sql": "WITH RECURSIVE chain(start_id, end_id, depth) AS ( SELECT prev_id, next_id, 1 FROM next_delivery WHERE prev_id = '{start_id}' UNION ALL SELECT c.start_id, n.next_id, c.depth + 1 FROM chain c JOIN next_delivery n ON n.prev_id = c.end_id WHERE c.depth < 3 ) SELECT '{start_id}' AS start, COUNT(*) AS reachable FROM chain WHERE end_id IS NOT NULL",
        "key_columns": ["start", "reachable"],
        "needs_start_id": True,
    },
]


def _resolve_start_delivery(graph):
    deliveries = sorted(graph.nodes_by_label("Delivery"), key=lambda n: n.id)
    for d in deliveries:
        if any(graph.neighbors(d.id, label="NEXT_DELIVERY", direction="out")):
            return d.id
    return deliveries[0].id if deliveries else "unknown"


def run_all(iters: int = 30):
    all_results = []
    summary_by_class: dict[str, dict] = {}

    for bm in BENCHMARKS:
        domain = bm["domain"]
        print(f"\n{'='*60}")
        print(f"  {bm['name']}")
        print(f"{'='*60}")

        if bm.get("use_cricsheet"):
            # Cricket domain — use cricsheet parser
            graph = PropertyGraph()
            validator = ShapeValidator(bm["shapes"])
            parser = CricsheetParser(graph, validator)
            for f in sorted(Path(bm["data_dir"]).glob("*.json")):
                parser.ingest_file(f)
            start_id = _resolve_start_delivery(graph)

            if bm["db"]:
                Path(bm["db"]).parent.mkdir(parents=True, exist_ok=True)
                if Path(bm["db"]).exists():
                    Path(bm["db"]).unlink()
                build_mirror(graph, bm["shapes"], bm["db"])

            # Run cricket direct queries through generic runner
            import sqlite3
            conn = sqlite3.connect(bm["db"]) if bm["db"] else None
            from gql_core.benchmark import _run_one as run_one_query
            from gql_core.query.semantic import set_schema_path
            set_schema_path(bm["shapes"])

            for q in CRICKET_QUERIES:
                q_copy = dict(q)
                if q.get("needs_start_id"):
                    q_copy["gql"] = q["gql"].format(start_id=start_id)
                    q_copy["sql"] = q["sql"].format(start_id=start_id)
                entry = run_one_query(graph, q_copy, {}, conn, iters, bm["shapes"], False)
                entry["domain"] = domain
                entry["query_class"] = q["query_class"]
                all_results.append(entry)
                cls = q["query_class"]
                summary_by_class.setdefault(cls, {"total": 0, "passed": 0, "failed": 0})
                summary_by_class[cls]["total"] += 1
                if entry["status"] == "pass":
                    summary_by_class[cls]["passed"] += 1
                else:
                    summary_by_class[cls]["failed"] += 1
                print(f"  [{entry['status'].upper()}] {entry['name']}  gql={entry['cypher']['median_ms']:.1f}ms"
                      + (f"  sql={entry['sql']['median_ms']:.1f}ms" if entry.get("sql") else ""))

            if conn:
                conn.close()

        else:
            # Generic domains
            graph = GqlGraph()
            validator = GqlValidator(bm["shapes"])
            ingester = GraphIngester(graph, validator)
            if bm.get("data_file"):
                ingester.ingest_file(bm["data_file"])

            if bm.get("db") and bm.get("suite"):
                Path(bm["db"]).parent.mkdir(parents=True, exist_ok=True)
                if Path(bm["db"]).exists():
                    Path(bm["db"]).unlink()

            if bm.get("suite"):
                # Pre-load suite to get query_class annotations
                import yaml as _yaml
                with open(bm["suite"]) as _f:
                    _suite_data = _yaml.safe_load(_f)
                _class_map = {q["name"]: q.get("query_class", "unknown")
                             for q in (_suite_data.get("queries") or [])}

                report = run_bm(
                    graph, bm["suite"],
                    shapes_path=bm["shapes"],
                    db_path=bm.get("db"),
                    iters=iters,
                    verbose=False,
                )
                for r in report["results"]:
                    r["domain"] = domain
                    r["query_class"] = _class_map.get(r["name"], "unknown")
                    all_results.append(r)
                    cls = r["query_class"]
                    summary_by_class.setdefault(cls, {"total": 0, "passed": 0, "failed": 0})
                    summary_by_class[cls]["total"] += 1
                    if r["status"] == "pass":
                        summary_by_class[cls]["passed"] += 1
                    else:
                        summary_by_class[cls]["failed"] += 1
                    sql_str = f"  sql={r['sql']['median_ms']:.1f}ms" if r.get("sql") else ""
                    print(f"  [{r['status'].upper()}] {r['name']}  gql={r['cypher']['median_ms']:.1f}ms{sql_str}")

    # ── Summary ──────────────────────────────────────────────────
    total = len(all_results)
    passed = sum(1 for r in all_results if r["status"] == "pass")
    failed = sum(1 for r in all_results if r["status"] == "fail")
    errors = sum(1 for r in all_results if r["status"] == "error")

    print(f"\n{'='*60}")
    print(f"  OVERALL: {passed}/{total} passed ({100*passed/total:.1f}%)")
    print(f"{'='*60}")
    print(f"\n  By query class:")
    for cls in sorted(summary_by_class.keys()):
        s = summary_by_class[cls]
        pct = 100 * s["passed"] / s["total"] if s["total"] else 0
        bar = "#" * int(pct / 5) + "." * (20 - int(pct / 5))
        print(f"  {cls:<20s}  {bar}  {s['passed']}/{s['total']} ({pct:.0f}%)")

    # Timing summary
    gql_times = [r["cypher"]["median_ms"] for r in all_results]
    sql_times = [r["sql"]["median_ms"] for r in all_results if r.get("sql")]
    print(f"\n  GQL median latency: {sorted(gql_times)[len(gql_times)//2]:.1f}ms")
    if sql_times:
        print(f"  SQL median latency: {sorted(sql_times)[len(sql_times)//2]:.1f}ms")

    return {
        "meta": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_queries": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "iters": iters,
        },
        "by_class": {cls: {"total": s["total"], "passed": s["passed"], "failed": s["failed"]}
                     for cls, s in summary_by_class.items()},
        "results": all_results,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=20)
    ap.add_argument("--out", type=str, default="benchmark/results/unified_results.json")
    args = ap.parse_args()

    report = run_all(iters=args.iters)

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWrote {out_path}")
