"""Download CypherBench test split, schemas and graphs from Hugging Face."""

from __future__ import annotations

import argparse
from pathlib import Path

REPO_ID = "megagonlabs/cypherbench"
CACHE_DIR = Path("benchmark/cache/cypherbench")
TEST_GRAPHS = ["nba", "flight_accident", "fictional_character", "company", "geography", "movie", "politics"]


def graph_path(graph: str, cache_dir: Path = CACHE_DIR) -> Path:
    return cache_dir / "graphs" / "simplekg" / f"{graph}_simplekg.json"


def download(graphs: list[str], cache_dir: Path = CACHE_DIR) -> None:
    from huggingface_hub import hf_hub_download

    files = ["test.json"] + [f"graphs/schemas/{g}_schema.json" for g in graphs]
    files += [f"graphs/simplekg/{g}_simplekg.json" for g in graphs]
    for f in files:
        p = hf_hub_download(REPO_ID, f, repo_type="dataset", local_dir=str(cache_dir))
        print(f"  {p}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--graphs", nargs="+", default=TEST_GRAPHS, choices=TEST_GRAPHS)
    args = ap.parse_args()
    download(args.graphs)


if __name__ == "__main__":
    main()
