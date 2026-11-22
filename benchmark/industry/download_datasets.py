"""Downloader and parser for Hetionet v1.0 (Himmelstein et al., eLife 2017),
from the official hetio/hetionet repository."""

from __future__ import annotations

import gzip
import io
import json
import urllib.request
from pathlib import Path

DATA_DIR = Path("benchmark/data")
HETIONET_URL = "https://github.com/hetio/hetionet/raw/master/hetnet/tsv/hetionet-v1.0-edges.sif.gz"
HETIONET_NODES_URL = "https://github.com/hetio/hetionet/raw/master/hetnet/tsv/hetionet-v1.0-nodes.tsv"


def download_hetionet(target_dir: Path = DATA_DIR) -> tuple[Path, Path]:
    """Downloads official Hetionet v1.0 nodes and edges TSV files."""
    target_dir.mkdir(parents=True, exist_ok=True)
    edges_file = target_dir / "hetionet-v1.0-edges.sif.gz"
    nodes_file = target_dir / "hetionet-v1.0-nodes.tsv"

    # Download edges
    if not edges_file.exists():
        print(f"[Download] Fetching official Hetionet v1.0 edges from: {HETIONET_URL}")
        req = urllib.request.Request(
            HETIONET_URL,
            headers={"User-Agent": "GQL-Core-Industry-Benchmark/0.2.0a1"},
        )
        with urllib.request.urlopen(req) as resp, open(edges_file, "wb") as out:
            out.write(resp.read())
        print(f"[Download] Saved edges to: {edges_file} ({edges_file.stat().st_size / 1024 / 1024:.2f} MB)")
    else:
        print(f"[Cache] Using existing Hetionet edges: {edges_file}")

    # Download nodes
    if not nodes_file.exists():
        print(f"[Download] Fetching official Hetionet v1.0 nodes from: {HETIONET_NODES_URL}")
        req = urllib.request.Request(
            HETIONET_NODES_URL,
            headers={"User-Agent": "GQL-Core-Industry-Benchmark/0.2.0a1"},
        )
        with urllib.request.urlopen(req) as resp, open(nodes_file, "wb") as out:
            out.write(resp.read())
        print(f"[Download] Saved nodes to: {nodes_file} ({nodes_file.stat().st_size / 1024 / 1024:.2f} MB)")
    else:
        print(f"[Cache] Using existing Hetionet nodes: {nodes_file}")

    return nodes_file, edges_file


def parse_hetionet_subgraph(
    nodes_file: Path,
    edges_file: Path,
    target_rel_types: set[str] | None = None,
    max_edges: int | None = None,
) -> tuple[dict[str, dict], list[tuple[str, str, str]]]:
    """Parses Hetionet nodes and edges.

    By default filters to pharmacological & mechanism relationships:
    - Compound - binds - Gene (CbG)
    - Compound - treats - Disease (CtD)
    - Compound - causes - Side Effect (CcSE)
    - Disease - associates - Gene (DaG)
    - Gene - interacts - Gene (GiG)
    """
    if target_rel_types is None:
        target_rel_types = {"CbG", "CtD", "CcSE", "DaG", "GiG"}

    # 1. Parse node definitions (id, name, kind)
    nodes: dict[str, dict] = {}
    with open(nodes_file, "r", encoding="utf-8") as f:
        header = f.readline().strip().split("\t")
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                node_id, name, kind = parts[0], parts[1], parts[2]
                nodes[node_id] = {"name": name, "kind": kind}

    # 2. Parse edges from compressed SIF
    edges: list[tuple[str, str, str]] = []
    with gzip.open(edges_file, "rt", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                src, rel, dst = parts[0], parts[1], parts[2]
                if target_rel_types and rel not in target_rel_types:
                    continue
                edges.append((src, rel, dst))
                if max_edges and len(edges) >= max_edges:
                    break

    return nodes, edges


if __name__ == "__main__":
    n_file, e_file = download_hetionet()
    nodes, edges = parse_hetionet_subgraph(n_file, e_file, max_edges=1000)
    print(f"\n[Validation] Successfully parsed {len(nodes)} nodes and {len(edges)} test edges from official Hetionet.")
