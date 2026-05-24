"""NL → GQL-Core benchmark harness.

For each of the 100 NL queries in benchmark.query_suite:
  1. Substitute {start_id} placeholder (RPQ queries only).
  2. Call Ollama to translate the NL question → GQL-Core.
  3. Parse the generated GQL-Core (catches syntax errors).
  4. Execute GQL-Core on the PropertyGraph.
  5. Execute the hidden SQL oracle on the SQLite mirror.
  6. Compare results → pass / fail.
  7. Record translation text, error (if any), timing.

Output: benchmark/results/suite_benchmark.json

Per-class accuracy is printed to stdout.

Usage:
    # Fixture smoke run (fast, no download needed):
    python -m benchmark.run_suite_benchmark \\
        --data tests/fixtures \\
        --model llama3

    # Full Pakistan corpus:
    python -m benchmark.run_suite_benchmark \\
        --data data/pakistan \\
        --db  data/cricket.db \\
        --model llama3 \\
        --verbose
"""

from __future__ import annotations

import argparse
import json
import signal
import sqlite3
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph.store import PropertyGraph
from ingestion.cricsheet_parser import CricsheetParser
from ingestion.validator import ShapeValidator
from query.executor import run as run_gql
from query.parser import parse as parse_gql
from benchmark.query_suite import SUITE
from benchmark.nl_to_gql import translate_clean, list_models
from benchmark.vs_sqlite import (
    _canonical_rows,
    _environment_meta,
    _rows_equal,
    _git_dirty,
    _git_rev,
    _methodology_meta,
    _select_start_delivery,
)
from scripts.build_sqlite_mirror import build_mirror

DEFAULT_OUT = Path("benchmark/results/suite_benchmark.json")
GQL_EXEC_TIMEOUT = 30  # seconds — prevents runaway traversals from hanging the benchmark


# ── Helpers ──────────────────────────────────────────────────────────────────


def _run_gql_with_timeout(gql: str, graph, timeout: int):
    """Execute GQL and raise RuntimeError if it exceeds *timeout* seconds."""
    def _handler(signum, frame):
        raise RuntimeError(f"GQL execution exceeded {timeout}s timeout")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout)
    try:
        return run_gql(gql, graph)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def _load_graph(data_dir: Path, shapes: Path) -> PropertyGraph:
    g = PropertyGraph()
    p = CricsheetParser(g, ShapeValidator(shapes))
    for f in sorted(data_dir.glob("*.json")):
        try:
            p.ingest_file(f)
        except Exception as exc:
            print(f"[warn] {f.name}: {exc}", file=sys.stderr)
    return g


def _resolve_question(q: dict, graph: PropertyGraph) -> tuple[str, dict]:
    """Return (question_with_start_id, resolved_query_dict).

    For RPQ queries with {start_id}, picks a real Delivery node id and
    substitutes it into the question text and the SQL string.
    The GQL-Core is generated from the question — the model receives the
    question with the actual delivery id already filled in.
    """
    if not q.get("needs_start_id"):
        return q["question"], q

    delivery = _select_start_delivery(graph)
    if delivery is None:
        return q["question"], q

    start_id = delivery.id
    resolved = dict(q)
    resolved["sql"] = q["sql"].format(start_id=start_id)
    resolved["_resolved_start_id"] = start_id
    question = q["question"].format(start_id=start_id)
    return question, resolved


# ── Per-query run ─────────────────────────────────────────────────────────────


def _run_one(
    q: dict,
    graph: PropertyGraph,
    conn: sqlite3.Connection,
    model: str,
    ollama_url: str,
    verbose: bool,
) -> dict:
    question, rq = _resolve_question(q, graph)

    result: dict = {
        "name": q["name"],
        "question": question,
        "query_class": q["query_class"],
        "ground_truth_note": q["ground_truth_note"],
        "generated_gql": None,
        "parse_error": None,
        "exec_error": None,
        "result_correct": False,
        "row_count": None,
        "translation_ms": None,
        "execution_ms": None,
    }
    if rq.get("_resolved_start_id"):
        result["resolved_start_id"] = rq["_resolved_start_id"]

    # ── Step 1: Translate NL → GQL ────────────────────────────────────────
    t0 = time.perf_counter()
    try:
        gql = translate_clean(question, model=model, ollama_url=ollama_url)
    except Exception as exc:
        result["exec_error"] = f"translation_failed: {exc}"
        if verbose:
            print(f"    TRANSLATION ERROR: {exc}")
        return result
    result["translation_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    result["generated_gql"] = gql

    # ── Step 2: Parse ─────────────────────────────────────────────────────
    try:
        parse_gql(gql)
    except Exception as exc:
        result["parse_error"] = str(exc)[:300]
        if verbose:
            print(f"    PARSE ERROR: {result['parse_error']}")
        return result

    # ── Step 3: Execute GQL ───────────────────────────────────────────────
    t1 = time.perf_counter()
    try:
        gql_rows = _run_gql_with_timeout(gql, graph, GQL_EXEC_TIMEOUT)
    except Exception as exc:
        result["exec_error"] = f"exec_gql: {str(exc)[:300]}"
        if verbose:
            print(f"    EXEC ERROR: {result['exec_error']}")
        return result
    result["execution_ms"] = round((time.perf_counter() - t1) * 1000, 2)

    # ── Step 4: Execute SQL oracle ────────────────────────────────────────
    try:
        sql_rows = conn.cursor().execute(rq["sql"]).fetchall()
    except Exception as exc:
        result["exec_error"] = f"exec_sql: {str(exc)[:300]}"
        return result

    # ── Step 5: Compare ───────────────────────────────────────────────────
    canon_gql = _canonical_rows(gql_rows, rq["key_columns"])
    canon_sql = _canonical_rows(sql_rows, rq["key_columns"])
    correct = _rows_equal(canon_gql, canon_sql)

    result["result_correct"] = correct
    result["row_count"] = len(canon_gql)

    if not correct:
        result["debug_gql_sample"] = [str(r) for r in canon_gql[:5]]
        result["debug_sql_sample"] = [str(r) for r in canon_sql[:5]]

    return result


# ── Main harness ──────────────────────────────────────────────────────────────


def run_suite_benchmark(
    graph: PropertyGraph,
    db_path: Path,
    *,
    model: str = "llama3",
    ollama_url: str = "http://localhost:11434",
    verbose: bool = False,
) -> dict:
    conn = sqlite3.connect(str(db_path))
    results: list[dict] = []
    passed = failed = 0

    for i, q in enumerate(SUITE, 1):
        if verbose:
            print(f"  [{i:03d}/{len(SUITE)}] {q['name']} ...", end=" ", flush=True)

        entry = _run_one(q, graph, conn, model, ollama_url, verbose)
        results.append(entry)

        if entry["result_correct"]:
            passed += 1
            if verbose:
                print(
                    f"OK   rows={entry['row_count']}  "
                    f"translate={entry['translation_ms']}ms  "
                    f"exec={entry['execution_ms']}ms"
                )
        else:
            failed += 1
            if verbose:
                reason = (
                    entry.get("parse_error")
                    or entry.get("exec_error")
                    or "result mismatch"
                )
                print(f"FAIL [{reason[:60]}]")

    conn.close()

    # Per-class summary
    class_summary: dict[str, dict] = {}
    for r in results:
        cls = r["query_class"]
        if cls not in class_summary:
            class_summary[cls] = {"total": 0, "passed": 0,
                                  "parse_errors": 0, "exec_errors": 0}
        class_summary[cls]["total"] += 1
        if r["result_correct"]:
            class_summary[cls]["passed"] += 1
        if r.get("parse_error"):
            class_summary[cls]["parse_errors"] += 1
        if r.get("exec_error"):
            class_summary[cls]["exec_errors"] += 1

    return {
        "meta": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "git_rev": _git_rev(),
            "model": model,
            "ollama_url": ollama_url,
            "total_queries": len(SUITE),
            "passed": passed,
            "failed": failed,
            "git_dirty": _git_dirty(),
            "environment": _environment_meta(),
            "graph_stats": graph.stats(),
            "methodology": _methodology_meta(),
        },
        "class_summary": class_summary,
        "results": results,
    }


# ── Pretty printer ────────────────────────────────────────────────────────────


def _print_summary(out: dict) -> None:
    meta = out["meta"]
    bar = "=" * 72
    print(f"\n{bar}")
    print(
        f"NL→GQL-Core Suite Benchmark — {meta['timestamp']}  "
        f"(git {meta['git_rev']})"
    )
    print(f"  model   : {meta['model']}")
    print(
        f"  graph   : {meta['graph_stats']['nodes']:,} nodes / "
        f"{meta['graph_stats']['edges']:,} edges"
    )
    print(
        f"  queries : {meta['total_queries']}   "
        f"passed: {meta['passed']}   failed: {meta['failed']}"
    )
    print(bar)

    print(f"\n{'Class':<16} {'Total':>5} {'Pass':>5} {'Acc':>6} {'ParseErr':>9} {'ExecErr':>8}")
    print("-" * 54)
    for cls, s in out["class_summary"].items():
        acc = f"{100*s['passed']//s['total']}%" if s["total"] else "—"
        print(
            f"  {cls:<14} {s['total']:>5} {s['passed']:>5} {acc:>6} "
            f"{s['parse_errors']:>9} {s['exec_errors']:>8}"
        )

    print(f"\n{'Query':<42} {'Class':<14} {'OK':>3} {'Translate ms':>13} {'Exec ms':>8}")
    print("-" * 84)
    for r in out["results"]:
        ok = "✓" if r["result_correct"] else "✗"
        tr = f"{r['translation_ms']:.0f}" if r["translation_ms"] is not None else "—"
        ex = f"{r['execution_ms']:.1f}" if r["execution_ms"] is not None else "—"
        print(f"  {r['name']:<40} {r['query_class']:<14} {ok:>3} {tr:>13} {ex:>8}")


# ── Entry point ───────────────────────────────────────────────────────────────


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=Path("data/pakistan"),
                    help="Directory of cricsheet JSON files")
    ap.add_argument("--shapes", type=Path, default=Path("ontology/shapes.yaml"))
    ap.add_argument("--db", type=Path, default=Path("data/cricket.db"),
                    help="SQLite mirror path (built automatically if absent)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--model", default=None,
                    help="Ollama model name (default: llama3 or $OLLAMA_MODEL)")
    ap.add_argument("--ollama-url", default="http://localhost:11434",
                    help="Ollama base URL")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--list-models", action="store_true",
                    help="Print available Ollama models and exit")
    args = ap.parse_args(argv)

    if args.list_models:
        models = list_models(args.ollama_url)
        if models:
            print("Available models:")
            for m in models:
                print(f"  {m}")
        else:
            print("No models found (is Ollama running?)")
        return 0

    model = args.model or __import__("os").environ.get("OLLAMA_MODEL", "llama3")

    # ── Load graph ────────────────────────────────────────────────────────
    if not args.data.exists() or not any(args.data.glob("*.json")):
        fallback = Path("tests/fixtures")
        print(f"[warn] {args.data} has no JSON; falling back to {fallback}", file=sys.stderr)
        args.data = fallback

    print(f"[load] ingesting {args.data}", file=sys.stderr)
    graph = _load_graph(args.data, args.shapes)
    print(f"[load] {graph.stats()}", file=sys.stderr)

    # ── Build SQLite mirror ────────────────────────────────────────────────
    print(f"[mirror] building SQLite mirror at {args.db}", file=sys.stderr)
    conn = build_mirror(graph, args.db)
    conn.close()

    # ── Run benchmark ──────────────────────────────────────────────────────
    print(
        f"[benchmark] translating {len(SUITE)} NL queries with {model}",
        file=sys.stderr,
    )
    out = run_suite_benchmark(
        graph,
        args.db,
        model=model,
        ollama_url=args.ollama_url,
        verbose=args.verbose or True,
    )

    # ── Save results ───────────────────────────────────────────────────────
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[done] wrote {args.out}", file=sys.stderr)

    _print_summary(out)
    return 0 if out["meta"]["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
