"""Shared schema loader for validator, semantic checker, and mirror builder.

Loads a shapes.yaml once and caches the result. All consumers that need
the schema parse tree share this single loader so the file is read at
most once per process.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@lru_cache(maxsize=8)
def load_shapes(path: str | Path) -> dict[str, Any]:
    """Load a shapes.yaml file, returning the parsed dict.

    Cached by resolved path — repeated calls with the same path hit the
    cache.  The cache is bounded (8 entries) so long-running processes
    that open many different schemas don't leak memory.
    """
    resolved = Path(path).resolve()
    with resolved.open() as f:
        return yaml.safe_load(f) or {}
