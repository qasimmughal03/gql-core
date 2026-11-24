"""Shared helpers: loading the test split, timed query execution, aggregation."""

from __future__ import annotations

import ctypes
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


def _stop_thread(t: threading.Thread) -> None:
    """Raise QueryTimeout inside a runaway query thread so it stops using CPU.

    An abandoned thread would otherwise keep running and slow every later query
    (the GIL is shared), turning one timeout into a run of them. The engine is
    pure Python, so the exception is delivered at the next bytecode boundary.
    """
    if t.ident is not None:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(t.ident), ctypes.py_object(QueryTimeout))
    t.join(60)


def run_with_timeout(cypher: str, graph: Any, timeout_s: float) -> list[dict]:
    """Run on a worker thread; a query still running after timeout_s is stopped and counted as a failure."""
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
        _stop_thread(t)
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
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no", "--", "gql_core", "benchmark", ":(exclude)benchmark/results"],
                           capture_output=True, text=True).stdout.strip()
    return f"{head}+dirty" if dirty else head


def engine_info() -> dict[str, Any]:
    """Which GQL-Core produced the results: version, and whether it is an installed package.

    ``location`` is relative to the Python environment (``<env>``) or the checkout (``<repo>``),
    so no local path is written. ``record_sha256`` fingerprints the installed files (the hash of
    the distribution's RECORD file), identical for everyone who installs the same wheel.
    """
    import hashlib
    import platform
    import sys
    from importlib import metadata

    import gql_core

    pkg_dir = Path(gql_core.__file__).resolve().parent
    repo = Path(__file__).resolve().parents[2]
    env = Path(sys.prefix).resolve()
    info: dict[str, Any] = {"package": "gql-core", "version": gql_core.__version__,
                            "python": platform.python_version()}
    if pkg_dir.is_relative_to(repo):
        info["source"] = "repository checkout"
        info["location"] = "<repo>/" + pkg_dir.relative_to(repo).as_posix()
    else:
        info["source"] = "installed package"
        info["location"] = ("<env>/" + pkg_dir.relative_to(env).as_posix()) if pkg_dir.is_relative_to(env) else "outside the environment"
    if info["source"] != "installed package":
        return info
    try:
        dist = metadata.distribution("gql-core")
        if Path(dist.locate_file("gql_core/__init__.py")).resolve() != Path(gql_core.__file__).resolve():
            info["installed_from"] = "not an installed distribution (imported from source)"
            return info
        info["distribution_version"] = dist.version
        direct = dist.read_text("direct_url.json")
        info["installed_from"] = "package index (PyPI)" if direct is None else (
            "editable checkout" if json.loads(direct).get("dir_info", {}).get("editable") else "local file")
        record = dist.read_text("RECORD")
        if record:
            info["record_sha256"] = hashlib.sha256(record.replace("\r\n", "\n").encode()).hexdigest()
    except metadata.PackageNotFoundError:
        info["installed_from"] = "not installed"
    return info
