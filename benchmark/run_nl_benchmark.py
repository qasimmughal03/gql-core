"""Natural-Language QA Benchmark harness.

Runs all 35 NL_QUERIES from benchmark.natural_queries against both the
GQL-Core engine and SQLite. For each query it records:
  - Cypher timing (median, p95, mean, stdev over `--iters` repeats)
  - SQL timing
  - Cross-engine result parity (Cypher rows == SQL rows)
  - Expressibility metrics (token ratio, recursion flag, query class)

Output: benchmark/results/nl_benchmark.json

Usage:
    # Full Pakistan corpus (after running download + build_sqlite_mirror):
    python -m benchmark.run_nl_benchmark \\
        --data data/pakistan \\
        --db data/cricket.db \\
        --iters 30

    # Fixture-only smoke run (no download needed):
    python -m benchmark.run_nl_benchmark \\
        --data tests/fixtures \\
        --iters 5
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import timeit
import statistics
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph.store import PropertyGraph
from ingestion.cricsheet_parser import CricsheetParser
from ingestion.validator import ShapeValidator
from query.executor import run as run_cypher
from benchmark.natural_queries import NL_QUERIES, expressibility
from benchmark.vs_sqlite import (
    _canonical_rows,
    _resolve_start_id,
    _rows_equal,
    _git_rev,
)
from scripts.build_sqlite_mirror import build_mirror

DEFAULT_RESULTS = Path("benchmark/results/nl_benchmark.json")


# ── Timing ───────────────────────────────────────────────────────────────


def _time(fn, iters: int) -> dict[str, float]:
    samples = timeit.repeat(fn, number=1, repeat=iters)
    return {
        "median_ms": round(statistics.median(samples) * 1000, 4),
        "p95_ms": round(sorted(samples)[max(0, int(0.95 * iters) - 1)] * 1000, 4),
        "mean_ms": round(statistics.mean(samples) * 1000, 4),
        "stdev_ms": round(statistics.stdev(samples) * 1000, 4) if iters > 1 else 0.0,
        "iters": iters,
    }


# ── Per-query execution ──────────────────────────────────────────────────


def _run_query(
    raw_q: dict,
    graph: PropertyGraph,
    conn: sqlite3.Connection,
    iters: int,
) -> dict:
    q = _resolve_start_id(raw_q, graph)
    cursor = conn.cursor()

    # Correctness check (single pass first)
    cypher_rows = run_cypher(q["cypher"], graph)
    sql_rows = cursor.execute(q["sql"]).fetchall()
    canon_c = _canonical_rows(cypher_rows, q["key_columns"])
    canon_s = _canonical_rows(sql_rows, q["key_columns"])
    correct = _rows_equal(canon_c, canon_s)

    # Warm-up
    run_cypher(q["cypher"], graph)
    conn.cursor().execute(q["sql"]).fetchall()

    # Timing
    cypher_timing = _time(lambda q=q: run_cypher(q["cypher"], graph), iters)
    sql_timing = _time(
        lambda q=q: conn.cursor().execute(q["sql"]).fetchall(), iters
    )

    entry: dict = {
        "name": q["name"],
        "question": q["question"],
        "query_class": q["query_class"],
        "ground_truth_note": q["ground_truth_note"],
        "row_count": len(canon_c),
        "result_correct": correct,
        "cypher": cypher_timing,
        "sql": sql_timing,
        "expressibility": expressibility(q),
    }
    if "_resolved_start_id" in q:
        entry["resolved_start_id"] = q["_resolved_start_id"]
    if not correct:
        # Attach first few rows from each engine for easier debugging.
        entry["debug_cypher_sample"] = [str(r) for r in canon_c[:5]]
        entry["debug_sql_sample"] = [str(r) for r in canon_s[:5]]
    return entry


# ── Main harness ─────────────────────────────────────────────────────────


def run_nl_benchmark(
    graph: PropertyGraph,
    db_path: Path,
    *,
    iters: int = 30,
    verbose: bool = False,
) -> dict:
    conn = sqlite3.connect(str(db_path))
    results: list[dict] = []
    passed = 0
    failed = 0

    for i, raw_q in enumerate(NL_QUERIES, 1):
        if verbose:
            print(
                f"  [{i:02d}/{len(NL_QUERIES)}] {raw_q['name']} ...",
                end=" ",
                flush=True,
            )
        entry = _run_query(raw_q, graph, conn, iters)
        results.append(entry)
        if entry["result_correct"]:
            passed += 1
            if verbose:
                print(
                    f"OK  rows={entry['row_count']}  "
                    f"cypher={entry['cypher']['median_ms']:.1f}ms  "
                    f"sql={entry['sql']['median_ms']:.1f}ms"
                )
        else:
            failed += 1
            if verbose:
                print(f"FAIL (result mismatch!)")

    conn.close()

    # Summary by query class
    class_summary: dict[str, dict] = {}
    for entry in results:
        cls = entry["query_class"]
        if cls not in class_summary:
            class_summary[cls] = {"total": 0, "passed": 0}
        class_summary[cls]["total"] += 1
        if entry["result_correct"]:
            class_summary[cls]["passed"] += 1

    return {
        "meta": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "git_rev": _git_rev(),
            "iters": iters,
            "total_queries": len(NL_QUERIES),
            "passed": passed,
            "failed": failed,
            "graph_stats": graph.stats(),
        },
        "class_summary": class_summary,
        "results": results,
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


def _print_summary(out: dict) -> None:
    meta = out["meta"]
    print(
        f"\n{'='*70}\n"
        f"NL Benchmark — {meta['timestamp']}  (git {meta['git_rev']})\n"
        f"  graph: {meta['graph_stats']['nodes']:,} nodes / "
        f"{meta['graph_stats']['edges']:,} edges\n"
        f"  iters per query: {meta['iters']}\n"
        f"  queries: {meta['total_queries']}   "
        f"passed: {meta['passed']}   failed: {meta['failed']}\n"
        f"{'='*70}"
    )
    print(
        f"\n{'Class':<22} {'Total':>5} {'Pass':>5} {'Ratio':>8}"
    )
    print("-" * 44)
    for cls, s in out["class_summary"].items():
        ratio = f"{s['passed']}/{s['total']}"
        print(f"  {cls:<20} {s['total']:>5} {s['passed']:>5} {ratio:>8}")

    print(f"\n{'Query':<42} {'Class':<16} {'Cypher ms':>10} {'SQL ms':>10} {'OK':>4}")
    print("-" * 86)
    for r in out["results"]:
        ok = "✓" if r["result_correct"] else "✗"
        print(
            f"  {r['name']:<40} {r['query_class']:<16} "
            f"{r['cypher']['median_ms']:>10.2f} "
            f"{r['sql']['median_ms']:>10.2f} "
            f"{ok:>4}"
        )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=Path("data/pakistan"))
    ap.add_argument("--shapes", type=Path, default=Path("ontology/shapes.yaml"))
    ap.add_argument("--db", type=Path, default=Path("data/cricket.db"))
    ap.add_argument("--out", type=Path, default=DEFAULT_RESULTS)
    ap.add_argument("--iters", type=int, default=30)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    if not args.data.exists() or not any(args.data.glob("*.json")):
        fallback = Path("tests/fixtures")
        print(
            f"[warn] {args.data} has no JSON; falling back to {fallback}",
            file=sys.stderr,
        )
        args.data = fallback

    print(f"[load] ingesting {args.data}", file=sys.stderr)
    graph = _load_graph(args.data, args.shapes)
    print(f"[load] {graph.stats()}", file=sys.stderr)

    print(f"[mirror] building SQLite mirror at {args.db}", file=sys.stderr)
    conn = build_mirror(graph, args.db)
    conn.close()

    print(f"[benchmark] running {len(NL_QUERIES)} NL queries × {args.iters} iters", file=sys.stderr)
    out = run_nl_benchmark(graph, args.db, iters=args.iters, verbose=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[done] wrote {args.out}", file=sys.stderr)

    _print_summary(out)
    return 0 if out["meta"]["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
