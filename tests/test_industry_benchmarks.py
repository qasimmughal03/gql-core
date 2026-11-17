"""Unified test runner for all authentic industry benchmarks."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_industry_benchmarks():
    scripts = [
        "benchmark/industry/run_courtlistener_eval.py",
        "benchmark/industry/run_supplychain_eval.py",
        "benchmark/industry/run_hetionet_eval.py",
    ]
    for s in scripts:
        full_path = ROOT / s
        assert full_path.exists(), f"Benchmark script missing: {full_path}"
        res = subprocess.run(
            [sys.executable, str(full_path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"{s} failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
