"""Cricket benchmark runner — uses the cricsheet parser with the generic
benchmark framework.

Usage::

    python examples/cricket/run_benchmark.py --data tests/fixtures --iters 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow importing from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from graph.store import PropertyGraph
from ingestion.cricsheet_parser import CricsheetParser
from ingestion.validator import ShapeValidator
from gql_core.benchmark import run_benchmark


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=Path("examples/cricket/fixtures"))
    ap.add_argument("--shapes", type=Path, default=Path("examples/cricket/shapes.yaml"))
    ap.add_argument("--suite", type=Path, default=Path("examples/cricket/benchmark/suite.yaml"))
    ap.add_argument("--db", type=Path, default=Path("examples/cricket/cricket.db"))
    ap.add_argument("--iters", type=int, default=30)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    print(f"[load] ingesting {args.data} ...", file=sys.stderr)
    graph = PropertyGraph()
    validator = ShapeValidator(args.shapes)
    parser_obj = CricsheetParser(graph, validator)
    for f in sorted(args.data.glob("*.json")):
        try:
            parser_obj.ingest_file(f)
        except Exception as exc:
            print(f"[warn] {f}: {exc}", file=sys.stderr)
    print(f"[load] {graph.stats()}", file=sys.stderr)

    report = run_benchmark(
        graph,
        args.suite,
        shapes_path=args.shapes,
        db_path=args.db,
        iters=args.iters,
        verbose=args.verbose,
    )

    # Console summary.
    passed = sum(1 for r in report["results"] if r["status"] == "pass")
    failed = sum(1 for r in report["results"] if r["status"] == "fail")
    errors = sum(1 for r in report["results"] if r["status"] == "error")
    print(f"\nSuite: {report['meta']['suite']}")
    for r in report["results"]:
        flag = "PASS" if r["status"] == "pass" else ("FAIL" if r["status"] == "fail" else "ERR ")
        gql_ms = r["cypher"]["median_ms"]
        sql_str = f"  sql={r['sql']['median_ms']:.1f}ms" if r.get("sql") else ""
        print(f"  [{flag}] {r['name']}  (gql={gql_ms:.1f}ms{sql_str})")
    print(f"\n{passed} passed, {failed} failed, {errors} errors, {len(report['results'])} total")
    return 0 if failed == 0 and errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
