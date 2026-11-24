"""Run a benchmark harness against the *installed* gql-core package, never this checkout's copy.

The harnesses live in this repository, so running them normally imports ``gql_core`` from the
checkout. This launcher removes the checkout from ``sys.path``, imports ``gql_core`` from the
environment (for example a clean venv with ``pip install gql-core==0.2.0a4``), refuses to go on
if that copy comes from the checkout, and only then makes ``benchmark`` importable. Each results
file records the engine that ran in its ``engine`` field.

Usage, from the repository root, with the environment's Python:

    python benchmark/run_published.py benchmark.cypherbench.run_nl2cypher --provider gemini ...
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _is_checkout(entry: str) -> bool:
    path = Path(entry or ".").resolve()
    return path == REPO or path.is_relative_to(REPO)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sys.path[:] = [p for p in sys.path if not _is_checkout(p)]
    import gql_core

    if Path(gql_core.__file__).resolve().is_relative_to(REPO):
        raise SystemExit(f"gql_core was imported from the checkout ({gql_core.__file__}); "
                         "install the package into this environment first")
    sys.path.append(str(REPO))  # after site-packages: benchmark/ is importable, gql_core stays installed

    from benchmark.cypherbench.common import engine_info

    print(f"engine: {engine_info()}", flush=True)
    target, sys.argv = sys.argv[1], sys.argv[1:]
    if target.endswith(".py"):
        runpy.run_path(target, run_name="__main__")
    else:
        runpy.run_module(target, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
