"""Real-data engine check: GQL-Core vs independent ground truth on Hetionet v1.0.

Skipped when the Hetionet files have not been downloaded
(python -m benchmark.industry.download_datasets).
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "benchmark" / "data"


@pytest.mark.skipif(
    not (DATA / "hetionet-v1.0-edges.sif.gz").exists() or not (DATA / "hetionet-v1.0-nodes.tsv").exists(),
    reason="Hetionet v1.0 data not downloaded",
)
def test_hetionet_engine_matches_independent_ground_truth():
    res = subprocess.run(
        [sys.executable, "-m", "benchmark.industry.run_full_hetionet_benchmark"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert res.returncode == 0, f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
