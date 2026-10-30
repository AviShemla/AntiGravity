from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DIRECT_SCRIPTS = (
    "audit_alpaca_candidate.py",
    "oracle_research_dataset_isolated_matrix_execute.py",
    "rebuild_market_features_to_turso.py",
    "stage_market_features_to_turso.py",
    "validate_claim_evidence_manifest.py",
    "validate_high_risk_evidence.py",
)


@pytest.mark.parametrize("script_name", DIRECT_SCRIPTS)
def test_absolute_script_help_from_unrelated_cwd(
    tmp_path: Path, script_name: str
) -> None:
    script = (ROOT / "scripts" / script_name).resolve()
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "ModuleNotFoundError" not in output
    assert "ImportError" not in output
