"""Tests asserting that domain demonstrations run cleanly."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_domain_demonstrations():
    domain_files = [
        "examples/domains/legal_kg.py",
        "examples/domains/software_supply_chain.py",
        "examples/domains/biomedical_network.py",
    ]
    for rel_path in domain_files:
        full_path = ROOT / rel_path
        assert full_path.exists(), f"Domain demonstration script missing: {full_path}"
        res = subprocess.run(
            [sys.executable, str(full_path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"{rel_path} failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
