"""Unified CLI for GQL-Core.

Entry point registered as ``gql-core`` via pyproject.toml console_scripts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from gql_core import __version__
from gql_core.graph import PropertyGraph
from gql_core.ingester import GraphIngester
from gql_core.mirror import build_mirror
from gql_core.query.executor import run as run_query
from gql_core.query.semantic import SemanticError
from gql_core.validator import ShapeValidator


def _load_graph(
    data_path: Path, shapes_path: Path, *, validate_only: bool = False
) -> tuple[PropertyGraph, GraphIngester, dict]:
    """Shared graph-loading helper for all subcommands."""
    graph = PropertyGraph()
    validator = ShapeValidator(shapes_path)
    ingester = GraphIngester(graph, validator)

    if data_path.is_dir():
        report = ingester.ingest_directory(data_path)
    else:
        n, e = ingester.ingest_file(data_path)
        report = {"files": 1, "nodes": n, "edges": e, "errors": []}

    return graph, ingester, report


# ── Subcommands ───────────────────────────────────────────────────────


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate a graph file/directory against a shapes schema."""
    data_path = Path(args.data)
    shapes_path = Path(args.schema)
    if not data_path.exists():
        print(f"Error: data path not found: {data_path}", file=sys.stderr)
        return 1
    if not shapes_path.exists():
        print(f"Error: schema not found: {shapes_path}", file=sys.stderr)
        return 1

    _, _, report = _load_graph(data_path, shapes_path)

    errors = report.get("errors", []) if isinstance(report, dict) else report.errors
    if errors:
        for err in errors:
            if isinstance(err, dict):
                print(
                    f"[{err.get('file', '?')}] {err.get('reason', '?')}: "
                    f"{err.get('message', '?')}"
                )
            else:
                print(str(err))
        print(f"\n{len(errors)} violation(s)")
        return 1
    print("OK")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Ingest graph data and print stats."""
    data_path = Path(args.data)
    shapes_path = Path(args.schema)

    graph, ingester, report = _load_graph(data_path, shapes_path)
    stats = graph.stats()

    # Also build mirror if requested.
    if args.db:
        db_path = Path(args.db)
        conn = build_mirror(graph, shapes_path, db_path)
        cur = conn.cursor()
        row_counts = {}
        for label in stats.get("by_label", {}):
            from gql_core.mirror import _snake

            table = _snake(label)
            try:
                row_counts[table] = cur.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            except Exception:
                pass
        for label in stats.get("edges_by_label", {}):
            from gql_core.mirror import _snake

            table = _snake(label.lower())
            try:
                row_counts[table] = cur.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            except Exception:
                pass
        conn.close()
        stats["mirror_row_counts"] = row_counts

    output = {
        "report": report if isinstance(report, dict) else report.as_dict(),
        "stats": stats,
    }
    print(json.dumps(output, indent=2, default=str))
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    """Run a GQL-Core query against a loaded graph."""
    data_path = Path(args.data)
    shapes_path = Path(args.schema)

    # Read query from file or positional argument.
    if args.file:
        query_src = Path(args.file).read_text()
    else:
        query_src = " ".join(args.query)

    graph, _, _ = _load_graph(data_path, shapes_path)

    try:
        rows = run_query(query_src, graph, schema_path=shapes_path)
    except SemanticError as exc:
        print(f"Semantic error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.table:
        _print_table(rows)
    else:
        print(json.dumps(rows, indent=2, default=str))
    return 0


def cmd_mirror(args: argparse.Namespace) -> int:
    """Build a SQLite mirror from a graph."""
    data_path = Path(args.data)
    shapes_path = Path(args.schema)
    db_path = Path(args.db)

    graph, _, _ = _load_graph(data_path, shapes_path)
    conn = build_mirror(graph, shapes_path, db_path)

    cur = conn.cursor()
    # Enumerate tables.
    tables = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    for (table,) in tables:
        count = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count} rows")
    conn.close()
    print(f"\nWrote {db_path}")
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    """Run a benchmark suite."""
    data_path = Path(args.data)
    shapes_path = Path(args.schema)
    suite_path = Path(args.suite)
    db_path = Path(args.db) if args.db else None

    graph, _, _ = _load_graph(data_path, shapes_path)

    from gql_core.benchmark import run_benchmark as run_bm

    report = run_bm(
        graph,
        suite_path,
        shapes_path=shapes_path,
        db_path=db_path,
        iters=args.iters,
        verbose=args.verbose,
    )

    # Write output.
    out_path = Path(args.out) if args.out else None
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, default=str))
        print(f"[done] wrote {out_path}", file=sys.stderr)

    # Console summary.
    print(f"\nSuite: {report['meta']['suite']}")
    print(f"Graph: {report['meta']['graph_stats']['nodes']} nodes, "
          f"{report['meta']['graph_stats']['edges']} edges")
    print()
    passed = 0
    failed = 0
    for r in report["results"]:
        flag = "PASS" if r["status"] == "pass" else ("FAIL" if r["status"] == "fail" else "ERR ")
        gql_ms = r["cypher"]["median_ms"]
        print(f"  [{flag}] {r['name']}  ({gql_ms:.1f} ms gql)")
        if r["status"] == "pass":
            passed += 1
        elif r["status"] == "fail":
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {len(report['results'])} total")
    return 0 if failed == 0 else 1


def cmd_version(_args: argparse.Namespace) -> int:
    """Print version and exit."""
    print(f"gql-core {__version__}")
    return 0


# ── Helpers ───────────────────────────────────────────────────────────


def _print_table(rows: list[dict]) -> None:
    if not rows:
        return
    keys = list(rows[0].keys())
    widths = {k: len(k) for k in keys}
    for row in rows:
        for k in keys:
            widths[k] = max(widths[k], len(str(row.get(k, ""))))
    sep = "  "
    header = sep.join(k.ljust(widths[k]) for k in keys)
    print(header)
    print("-" * len(header))
    for row in rows:
        print(sep.join(str(row.get(k, "")).ljust(widths[k]) for k in keys))


# ── Main ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        "gql-core",
        description="Generic property-graph query engine with formal GQL grammar.",
    )
    ap.add_argument(
        "--version", action="version", version=f"gql-core {__version__}"
    )
    sub = ap.add_subparsers(dest="command")

    # validate
    p = sub.add_parser("validate", help="Validate a graph against a shapes schema")
    p.add_argument("--schema", required=True, help="Path to shapes.yaml")
    p.add_argument("--data", required=True, help="Graph JSON file or directory")
    p.set_defaults(func=cmd_validate)

    # ingest
    p = sub.add_parser("ingest", help="Ingest a graph and print stats")
    p.add_argument("--schema", required=True, help="Path to shapes.yaml")
    p.add_argument("--data", required=True, help="Graph JSON file or directory")
    p.add_argument("--db", default=None, help="Optional: also build SQLite mirror at this path")
    p.set_defaults(func=cmd_ingest)

    # query
    p = sub.add_parser("query", help="Run a GQL-Core query")
    p.add_argument("--schema", required=True, help="Path to shapes.yaml")
    p.add_argument("--data", required=True, help="Graph JSON file or directory")
    p.add_argument("--file", default=None, help="Read query from file")
    p.add_argument("--table", action="store_true", help="Output as aligned text table")
    p.add_argument(
        "query", nargs="*", help="GQL-Core query string (or use --file)"
    )
    p.set_defaults(func=cmd_query)

    # mirror
    p = sub.add_parser("mirror", help="Build SQLite mirror from a graph")
    p.add_argument("--schema", required=True, help="Path to shapes.yaml")
    p.add_argument("--data", required=True, help="Graph JSON file or directory")
    p.add_argument("--db", required=True, help="Output SQLite database path")
    p.set_defaults(func=cmd_mirror)

    # benchmark
    p = sub.add_parser("benchmark", help="Run a benchmark suite")
    p.add_argument("--schema", required=True, help="Path to shapes.yaml")
    p.add_argument("--data", required=True, help="Graph JSON file or directory")
    p.add_argument("--suite", required=True, help="Benchmark suite YAML file")
    p.add_argument("--db", default=None, help="SQLite mirror path (auto-built if needed)")
    p.add_argument("--out", default=None, help="Write JSON report to file")
    p.add_argument("--iters", type=int, default=50, help="Timing iterations (default: 50)")
    p.add_argument("--verbose", action="store_true", help="Print per-query details")
    p.set_defaults(func=cmd_benchmark)

    # version
    p = sub.add_parser("version", help="Print version and exit")
    p.set_defaults(func=cmd_version)

    args = ap.parse_args(argv)
    if args.command is None:
        ap.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
