"""Benchmark harness: GQL-Core vs SQLite.

For each paired query in benchmark.queries.QUERIES:
  1. Run both engines once to capture results (correctness check).
  2. Time each with timeit.repeat (number=1, repeat=N).
  3. Record median, p95, mean, stdev.
  4. Compute expressibility metrics.

Output: benchmark/results/results.json with a row per query plus a meta
block (timestamp, hardware, git rev, fixture/corpus stats).
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import subprocess
import sys
import time
import timeit
from pathlib import Path
from typing import Any

from graph.store import PropertyGraph
from ingestion.cricsheet_parser import CricsheetParser
from ingestion.validator import ShapeValidator
from query.executor import run as run_cypher
from benchmark.queries import QUERIES, expressibility
from benchmark.logical_reasoning import (
    LR_QUERIES,
    expressibility as lr_expressibility,
)
from scripts.build_sqlite_mirror import build_mirror

DEFAULT_RESULTS = Path("benchmark/results/results.json")


def _resolve_start_id(query: dict, graph: PropertyGraph) -> dict:
    """Substitute the `{start_id}` placeholder with a real Delivery id.

    Picks any node whose label is Delivery so the query never points at a
    non-existent id (which would create the Cypher-empty vs SQL-zero-row
    semantic mismatch noted in the README). Returns a shallow-copied query
    with the placeholder filled in; the original dict is untouched.
    """
    if not query.get("needs_start_id"):
        return query
    delivery = next(iter(graph.nodes_by_label("Delivery")), None)
    if delivery is None:
        return query
    start_id = delivery.id
    q = dict(query)
    q["cypher"] = q["cypher"].format(start_id=start_id)
    q["sql"] = q["sql"].format(start_id=start_id)
    q["_resolved_start_id"] = start_id
    return q


def _git_rev() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip() or "unknown"
    except Exception:
        pass
    return "unknown"


def _canonical_rows(rows: list, key_columns: tuple[str, ...]) -> list[tuple]:
    """Return a sorted list-of-tuples for deterministic comparison."""
    canon: list[tuple] = []
    for r in rows:
        if isinstance(r, dict):
            canon.append(tuple(r.get(c) for c in key_columns))
        else:
            canon.append(tuple(r))
    canon.sort(key=lambda t: tuple((v is None, v if v is not None else "") for v in t))
    return canon


def _rows_equal(a: list[tuple], b: list[tuple]) -> bool:
    if len(a) != len(b):
        return False
    for ra, rb in zip(a, b):
        if len(ra) != len(rb):
            return False
        for va, vb in zip(ra, rb):
            if isinstance(va, float) or isinstance(vb, float):
                if va is None or vb is None:
                    if va != vb:
                        return False
                elif not math.isclose(va, vb, rel_tol=1e-6):
                    return False
            elif va != vb:
                return False
    return True


def _time(fn, iters: int) -> dict[str, float]:
    samples = timeit.repeat(fn, number=1, repeat=iters)
    return {
        "median_ms": round(statistics.median(samples) * 1000, 4),
        "p95_ms": round(sorted(samples)[max(0, int(0.95 * iters) - 1)] * 1000, 4),
        "mean_ms": round(statistics.mean(samples) * 1000, 4),
        "stdev_ms": round(statistics.stdev(samples) * 1000, 4) if iters > 1 else 0.0,
        "iters": iters,
    }


def _run_class(
    queries: list[dict],
    expressibility_fn,
    graph: PropertyGraph,
    cursor,
    conn,
    iters: int,
) -> list[dict]:
    rows_out: list[dict] = []
    for raw_q in queries:
        q = _resolve_start_id(raw_q, graph)
        cypher_rows = run_cypher(q["cypher"], graph)
        sql_rows = cursor.execute(q["sql"]).fetchall()
        canon_cypher = _canonical_rows(cypher_rows, q["key_columns"])
        canon_sql = _canonical_rows(sql_rows, q["key_columns"])
        correct = _rows_equal(canon_cypher, canon_sql)

        # Warm up once each to avoid first-call effects.
        run_cypher(q["cypher"], graph)
        cursor.execute(q["sql"]).fetchall()

        cypher_timing = _time(lambda q=q: run_cypher(q["cypher"], graph), iters)
        sql_timing = _time(lambda q=q: conn.cursor().execute(q["sql"]).fetchall(), iters)

        entry = {
            "name": q["name"],
            "purpose": q["purpose"],
            "row_count": len(canon_cypher),
            "result_correct": correct,
            "cypher": cypher_timing,
            "sql": sql_timing,
            "expressibility": expressibility_fn(q),
        }
        if "_resolved_start_id" in q:
            entry["resolved_start_id"] = q["_resolved_start_id"]
        rows_out.append(entry)
    return rows_out


def benchmark(graph: PropertyGraph, db_path: Path, *, iters: int = 100) -> dict:
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    direct = _run_class(QUERIES, expressibility, graph, cursor, conn, iters)
    reasoning = _run_class(LR_QUERIES, lr_expressibility, graph, cursor, conn, iters)
    conn.close()
    return {
        "meta": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "git_rev": _git_rev(),
            "iters": iters,
            "graph_stats": graph.stats(),
        },
        "direct_queries": direct,
        "logical_reasoning": reasoning,
    }


def _load_graph(data_dir: Path, shapes: Path) -> PropertyGraph:
    g = PropertyGraph()
    p = CricsheetParser(g, ShapeValidator(shapes))
    for f in sorted(data_dir.glob("*.json")):
        try:
            p.ingest_file(f)
        except Exception as exc:
            print(f"[warn] {f}: {exc}", file=sys.stderr)
    return g


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=Path("data/pakistan"))
    ap.add_argument("--shapes", type=Path, default=Path("ontology/shapes.yaml"))
    ap.add_argument("--db", type=Path, default=Path("data/cricket.db"))
    ap.add_argument("--out", type=Path, default=DEFAULT_RESULTS)
    ap.add_argument("--iters", type=int, default=100)
    args = ap.parse_args(argv)

    if not args.data.exists() or not any(args.data.glob("*.json")):
        # Fall back to the test fixtures so the harness has something to run on.
        fallback = Path("tests/fixtures")
        print(
            f"[warn] {args.data} has no JSON; falling back to {fallback}",
            file=sys.stderr,
        )
        args.data = fallback

    print(f"[load] ingesting {args.data}", file=sys.stderr)
    graph = _load_graph(args.data, args.shapes)
    print(f"[load] {graph.stats()}", file=sys.stderr)

    print(f"[mirror] writing {args.db}", file=sys.stderr)
    conn = build_mirror(graph, args.db)
    conn.close()

    print(f"[benchmark] iters={args.iters}", file=sys.stderr)
    out = benchmark(graph, args.db, iters=args.iters)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, default=str))
    print(f"[done] wrote {args.out}", file=sys.stderr)

    # Console summary.
    print(json.dumps(
        {"direct_queries": out["direct_queries"], "logical_reasoning": out["logical_reasoning"]},
        indent=2,
        default=str,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
