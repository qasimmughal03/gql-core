"""Generic benchmark runner for GQL-Core.

Runs a benchmark suite (YAML) against a PropertyGraph and optionally an
SQLite mirror. Supports three correctness tracks:

  1. *expected* — explicit ground-truth rows in the suite.
  2. *sql* — paired SQL query run against the mirror (parity check).
  3. *neither* — timing-only (status: 'timed').

Usage::

    from gql_core.benchmark import run_benchmark
    report = run_benchmark(graph, "suite.yaml", shapes="shapes.yaml", db="out.db")
"""

from __future__ import annotations

import json
import math
import platform
import sqlite3
import statistics
import subprocess
import time
import timeit
from pathlib import Path
from typing import Any

import yaml

from gql_core.graph import PropertyGraph
from gql_core.mirror import build_mirror
from gql_core.query.executor import execute, run as run_query
from gql_core.query.parser import parse
from gql_core.query.planner import plan as plan_query
from gql_core.query.semantic import validate_query


# ═══════════════════════════════════════════════════════════════════════
# Suite loading
# ═══════════════════════════════════════════════════════════════════════


class SuiteLoadError(ValueError):
    """Raised when a benchmark suite YAML is malformed."""


def load_suite(path: str | Path) -> dict:
    """Load and validate a benchmark suite YAML file.

    Returns the parsed dict with these keys guaranteed:
      name, queries (list of dicts, each with 'name' and 'gql').
    """
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise SuiteLoadError("Suite must be a YAML mapping")
    if "name" not in data:
        raise SuiteLoadError("Suite missing required key 'name'")
    queries = data.get("queries")
    if not isinstance(queries, list) or len(queries) == 0:
        raise SuiteLoadError("Suite must have a non-empty 'queries' list")

    for i, q in enumerate(queries):
        if "name" not in q:
            raise SuiteLoadError(f"Query {i} missing 'name'")
        if "gql" not in q:
            raise SuiteLoadError(f"Query {q['name']!r} missing 'gql'")

    return data


def resolve_params(suite: dict, graph: PropertyGraph) -> dict[str, str]:
    """Resolve parameter placeholders (e.g. {start_id}) against the graph.

    Suite ``params`` entries describe how to pick a value::

        params:
          - name: start_id
            resolve:
              label: Delivery
              has_out_edge: NEXT_DELIVERY
              order: id
    """
    resolved: dict[str, str] = {}
    for param in suite.get("params") or ():
        name = param["name"]
        spec = param.get("resolve") or {}
        resolved[name] = _resolve_param(graph, spec)
    return resolved


def _resolve_param(graph: PropertyGraph, spec: dict) -> str:
    label = spec.get("label")
    has_out_edge = spec.get("has_out_edge")
    order = spec.get("order", "id")

    if label is None:
        raise SuiteLoadError("resolve spec missing 'label'")

    candidates = sorted(graph.nodes_by_label(label), key=lambda n: n.id)
    if has_out_edge:
        candidates = [
            n
            for n in candidates
            if any(
                graph.neighbors(n.id, label=has_out_edge, direction="out")
            )
        ]
    if not candidates:
        raise SuiteLoadError(
            f"No nodes of label {label!r}"
            + (f" with out-edge {has_out_edge!r}" if has_out_edge else "")
        )
    if order == "first":
        return candidates[0].id
    return candidates[0].id  # sorted → first by id


# ═══════════════════════════════════════════════════════════════════════
# Canonical row comparison
# ═══════════════════════════════════════════════════════════════════════


def canonical_rows(
    rows: list, key_columns: tuple[str, ...] | None = None
) -> list[tuple]:
    """Return a deterministically-sorted list of tuples."""
    canon: list[tuple] = []
    for r in rows:
        if isinstance(r, dict):
            if key_columns and all(c in r for c in key_columns):
                canon.append(tuple(r[c] for c in key_columns))
            else:
                canon.append(tuple(r.values()))
        else:
            canon.append(tuple(r))
    canon.sort(
        key=lambda t: tuple(
            (v is None, v if v is not None else "") for v in t
        )
    )
    return canon


def rows_equal(a: list[tuple], b: list[tuple]) -> bool:
    """Compare two canonical row sets with float tolerance."""
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


# ═══════════════════════════════════════════════════════════════════════
# Timing helpers
# ═══════════════════════════════════════════════════════════════════════


def _time(fn, iters: int) -> dict[str, float]:
    samples = timeit.repeat(fn, number=1, repeat=iters)
    return {
        "median_ms": round(statistics.median(samples) * 1000, 4),
        "p95_ms": round(
            sorted(samples)[max(0, int(0.95 * iters) - 1)] * 1000, 4
        ),
        "mean_ms": round(statistics.mean(samples) * 1000, 4),
        "stdev_ms": round(statistics.stdev(samples) * 1000, 4)
        if iters > 1
        else 0.0,
        "iters": iters,
    }


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


# ═══════════════════════════════════════════════════════════════════════
# Main runner
# ═══════════════════════════════════════════════════════════════════════


def run_benchmark(
    graph: PropertyGraph,
    suite_path: str | Path,
    *,
    shapes_path: str | Path | None = None,
    db_path: str | Path | None = None,
    iters: int = 50,
    verbose: bool = False,
) -> dict:
    """Run a benchmark suite.

    Parameters
    ----------
    graph : PropertyGraph
        Loaded graph.
    suite_path : Path
        YAML benchmark suite file.
    shapes_path : Path, optional
        shapes.yaml for semantic validation.
    db_path : Path, optional
        SQLite mirror path. If provided and any query has ``sql``, the
        mirror is built (or reused if it already exists).
    iters : int
        Number of timing iterations per query.
    verbose : bool
        Print progress to stderr.

    Returns
    -------
    dict
        Report with ``meta`` and ``results`` keys.
    """
    suite = load_suite(suite_path)
    params = resolve_params(suite, graph)

    has_sql = any(q.get("sql") for q in suite["queries"])
    conn: sqlite3.Connection | None = None
    if has_sql and db_path is not None:
        db_path = Path(db_path)
        if not db_path.exists() and shapes_path is not None:
            if verbose:
                import sys

                print(f"[mirror] building {db_path} ...", file=sys.stderr)
            build_mirror(graph, shapes_path, db_path)
        conn = sqlite3.connect(str(db_path))

    results: list[dict] = []
    for q in suite["queries"]:
        entry = _run_one(graph, q, params, conn, iters, shapes_path, verbose)
        results.append(entry)

    if conn is not None:
        conn.close()

    return {
        "meta": {
            "suite": suite["name"],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "git_rev": _git_rev(),
            "iters": iters,
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            "graph_stats": graph.stats(),
        },
        "results": results,
    }


def _run_one(
    graph: PropertyGraph,
    q: dict,
    params: dict[str, str],
    conn: sqlite3.Connection | None,
    iters: int,
    shapes_path: str | Path | None,
    verbose: bool,
) -> dict:
    name = q["name"]
    gql_src = q["gql"].format(**params) if params else q["gql"]
    key_columns: tuple[str, ...] = tuple(q.get("key_columns") or ())

    # Parse + plan once.
    parsed = parse(gql_src)
    if shapes_path:
        validate_query(parsed, schema_path=shapes_path)
    plan_obj = plan_query(parsed, graph)

    # Execute for correctness.
    try:
        gql_rows = execute(plan_obj, graph)
        gql_error = None
    except Exception as exc:
        gql_rows = []
        gql_error = f"{type(exc).__name__}: {exc}"

    canon_gql = canonical_rows(gql_rows, key_columns or None)

    # --- Expected results ---
    correct_expected: bool | None = None
    expected = q.get("expected")
    if expected is not None:
        exp_rows = expected if isinstance(expected, list) else []
        exp_cols = tuple(q.get("expected_columns") or ())
        canon_exp = canonical_rows(
            [dict(zip(exp_cols, r)) if exp_cols and isinstance(r, list) else r
             for r in exp_rows],
            exp_cols or None,
        )
        correct_expected = rows_equal(canon_gql, canon_exp)
        if verbose and not correct_expected:
            import sys

            print(
                f"  [{name}] expected mismatch:\n"
                f"    gql={canon_gql}\n    exp={canon_exp}",
                file=sys.stderr,
            )

    # --- SQL parity ---
    correct_sql: bool | None = None
    sql_src = q.get("sql")
    if sql_src and conn is not None:
        sql_src_resolved = sql_src.format(**params) if params else sql_src
        try:
            cur = conn.cursor()
            sql_rows = cur.execute(sql_src_resolved).fetchall()
            sql_error = None
        except Exception as exc:
            sql_rows = []
            sql_error = f"{type(exc).__name__}: {exc}"
        canon_sql = canonical_rows(sql_rows, key_columns or None)
        correct_sql = rows_equal(canon_gql, canon_sql)
        if verbose and not correct_sql:
            import sys

            print(
                f"  [{name}] sql mismatch:\n"
                f"    gql={canon_gql}\n    sql={canon_sql}",
                file=sys.stderr,
            )
    else:
        sql_error = None

    # --- Status ---
    if gql_error:
        status = "error"
    elif correct_expected is not None:
        status = "pass" if correct_expected else "fail"
    elif correct_sql is not None:
        status = "pass" if correct_sql else "fail"
    else:
        status = "timed"

    # --- Timing ---
    # Warm up.
    try:
        run_query(gql_src, graph, schema_path=shapes_path)
        execute(plan_obj, graph)
    except Exception:
        pass

    cypher_timing = _time(
        lambda: run_query(gql_src, graph, schema_path=shapes_path), iters
    )
    cypher_execute_timing = _time(lambda: execute(plan_obj, graph), iters)
    sql_timing = None
    if sql_src and conn is not None:
        sql_timing = _time(
            lambda s=sql_src_resolved: conn.cursor()
            .execute(s)
            .fetchall(),
            iters,
        )

    entry: dict = {
        "name": name,
        "purpose": q.get("purpose", q.get("description", "")),
        "status": status,
        "row_count": len(canon_gql),
        "cypher": cypher_timing,
        "cypher_execute": cypher_execute_timing,
    }
    if gql_error:
        entry["gql_error"] = gql_error
    if correct_expected is not None:
        entry["correct_expected"] = correct_expected
    if correct_sql is not None:
        entry["correct_sql"] = correct_sql
    if sql_timing is not None:
        entry["sql"] = sql_timing
    if sql_error:
        entry["sql_error"] = sql_error

    return entry
