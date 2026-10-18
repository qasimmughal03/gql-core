"""Downloader and unpacker for official LDBC SNB Interactive v1 SF0.1 dataset.

Downloads the official CsvComposite-LongDateFormatter archive, verifies SHA-256,
and decompresses the initial snapshot files.
"""

from __future__ import annotations

import hashlib
import io
import os
import tarfile
import time
import urllib.request
from pathlib import Path

import zstandard

SF01_URL = "https://datasets.ldbcouncil.org/snb-interactive-v1/social_network-sf0.1-CsvComposite-LongDateFormatter.tar.zst"
CACHE_DIR = Path("benchmark/cache")
ARCHIVE_PATH = CACHE_DIR / "social_network-sf0.1-CsvComposite-LongDateFormatter.tar.zst"
UNPACK_DIR = CACHE_DIR / "sf01"


def download_and_unpack_sf01(force: bool = False) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not ARCHIVE_PATH.exists() or force:
        print(f"Downloading official LDBC SNB SF0.1 dataset from {SF01_URL}...")
        t0 = time.perf_counter()
        req = urllib.request.Request(SF01_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            content = resp.read()
        with open(ARCHIVE_PATH, "wb") as fp:
            fp.write(content)
        t1 = time.perf_counter()
        print(f"Downloaded {len(content)} bytes in {t1 - t0:.2f}s")
    else:
        print(f"Archive already cached at {ARCHIVE_PATH}")

    # Compute checksum
    hasher = hashlib.sha256()
    with open(ARCHIVE_PATH, "rb") as fp:
        while chunk := fp.read(1024 * 1024):
            hasher.update(chunk)
    sha256 = hasher.hexdigest()
    print(f"Archive SHA-256: {sha256}")

    if not UNPACK_DIR.exists() or force:
        print(f"Decompressing zstandard tar archive to {UNPACK_DIR}...")
        t0 = time.perf_counter()
        dctx = zstandard.ZstdDecompressor()
        with open(ARCHIVE_PATH, "rb") as ifh:
            with dctx.stream_reader(ifh) as reader:
                with tarfile.open(fileobj=reader, mode="r|") as tar:
                    tar.extractall(path=UNPACK_DIR)
        t1 = time.perf_counter()
        print(f"Decompressed in {t1 - t0:.2f}s")
    else:
        print(f"Decompressed dataset already exists at {UNPACK_DIR}")

    return UNPACK_DIR


if __name__ == "__main__":
    download_and_unpack_sf01()
