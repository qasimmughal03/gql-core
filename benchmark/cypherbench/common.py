"""Shared helpers: loading the test split, timed query execution, aggregation."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any

from gql_core import run

from benchmark.cypherbench.download import CACHE_DIR

RETURN_PATTERN_MAPPING = {  # from the official cypherbench/evaluate.py
    "n_name": "n_name",
    "n_prop": "n_prop_combined",
    "n_name_prop": "n_prop_combined",
    "n_prop_distinct": "n_prop_combined",
    "n_prop_array_distinct": "n_prop_combined",
    "n_order_by": "n_order_by",
    "n_argmax": "n_argmax",
    "n_where": "n_where",
    "n_agg": "n_agg",
    "n_group_by": "n_group_by",
}


def load_test(cache_dir: Path = CACHE_DIR) -> list[dict]:
    with open(cache_dir / "test.json", encoding="utf-8") as f:
        return json.load(f)


class QueryTimeout(Exception):
    pass


def run_with_timeout(cypher: str, graph: Any, timeout_s: float) -> list[dict]:
    """Run on a daemon thread; a timed-out query is abandoned and counted as a failure."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["rows"] = run(cypher, graph)
        except BaseException as exc:  # noqa: BLE001 - report every engine failure
            box["exc"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise QueryTimeout(f"query exceeded {timeout_s}s")
    if "exc" in box:
        raise box["exc"]
    return box["rows"]


def avg(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 4) if xs else float("nan")


def breakdown(items: list[dict], metric: str) -> dict[str, dict[str, float]]:
    """Per-graph / per-match-category / per-return-pattern averages, as in the official evaluate.py."""

    def agg(key_fn) -> dict[str, float]:
        groups: dict[str, list[float]] = {}
        for it in items:
            k = key_fn(it)
            if k is not None:
                groups.setdefault(k, []).append(it[metric])
        return {k: avg(v) for k, v in sorted(groups.items())}

    return {
        "by_graph": agg(lambda it: it["graph"]),
        "by_match": agg(lambda it: it["match_category"]),
        "by_return": agg(lambda it: RETURN_PATTERN_MAPPING.get(it["return_pattern_id"])),
    }


def git_commit() -> str:
    """Short HEAD hash, with "+dirty" when tracked engine/benchmark code has uncommitted changes."""
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no", "--", "gql_core", "benchmark"],
                           capture_output=True, text=True).stdout.strip()
    return f"{head}+dirty" if dirty else head
