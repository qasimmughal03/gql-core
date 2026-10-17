"""One-shot cricsheet downloader.

Streams a country zip from cricsheet.org to a temp file, then unzips into
data/pakistan/. Idempotent: if the destination already contains > 50 .json
files, the download is skipped (run with --force to re-download).

Usage:
    python scripts/download_cricsheet.py [--url URL] [--dest data/pakistan] [--force]
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

# Allow plain `python scripts/download_cricsheet.py` invocation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

DEFAULT_URL = "https://cricsheet.org/downloads/pakistan_json.zip"
DEFAULT_DEST = Path("data/pakistan")
SKIP_THRESHOLD = 50


def download(url: str, dest: Path, *, force: bool = False) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    existing = list(dest.glob("*.json"))
    if not force and len(existing) > SKIP_THRESHOLD:
        print(
            f"[skip] {dest} already has {len(existing)} JSON files "
            f"(> {SKIP_THRESHOLD}); pass --force to re-download.",
            file=sys.stderr,
        )
        return 0

    print(f"[download] {url} → {dest}", file=sys.stderr)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        with requests.get(url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            written = 0
            for chunk in resp.iter_content(chunk_size=1 << 16):
                if not chunk:
                    continue
                tmp.write(chunk)
                written += len(chunk)
                if total:
                    pct = 100 * written / total
                    print(
                        f"\r[download] {written / 1e6:.1f}MB / {total / 1e6:.1f}MB ({pct:.1f}%)",
                        end="",
                        file=sys.stderr,
                    )
        zip_path = Path(tmp.name)
    print("", file=sys.stderr)

    print(f"[unzip] {zip_path} → {dest}", file=sys.stderr)
    count = 0
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            if not member.filename.endswith(".json"):
                continue
            target = dest / Path(member.filename).name
            with zf.open(member) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
            count += 1
    zip_path.unlink(missing_ok=True)
    print(f"[done] wrote {count} JSON files to {dest}", file=sys.stderr)
    return count


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    download(args.url, args.dest, force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
