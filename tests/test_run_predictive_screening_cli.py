import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_predictive_screening.py"


class PredictiveScreeningCliTests(unittest.TestCase):
    def test_material_statistical_arguments_are_required(self):
        result = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--source-session-date",
                "2026-08-21",
                "--cutoff-utc",
                "2026-08-23T06:46:36+00:00",
                "--code-version",
                "test",
                "--candidate-lags",
                "1,2,5,7",
                "--purge-sessions",
                "7",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        for argument in (
            "--min-depth",
            "--max-depth",
            "--min-train-sessions",
            "--test-sessions",
            "--outer-folds",
            "--min-oos-sessions",
            "--min-fit-observations",
            "--signal-lookback-sessions",
            "--model-family",
        ):
            self.assertIn(argument, result.stderr)
        self.assertIn("--training-window-sessions", result.stderr)
        self.assertIn("--expanding-training-window", result.stderr)

    def test_help_does_not_require_database_credentials(self):
        result = subprocess.run(
            [sys.executable, str(RUNNER), "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--candidate-lags", result.stdout)
        self.assertIn("--expanding-training-window", result.stdout)

    def test_impossible_nested_fold_fails_before_turso_access(self):
        environment = os.environ.copy()
        environment.pop("TURSO_DATABASE_URL", None)
        environment.pop("TURSO_AUTH_TOKEN", None)
        result = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--source-session-date",
                "2026-08-21",
                "--cutoff-utc",
                "2026-08-23T06:46:36+00:00",
                "--code-version",
                "test",
                "--min-depth",
                "1",
                "--max-depth",
                "5",
                "--candidate-lags",
                "1,2,3,4,5",
                "--purge-sessions",
                "7",
                "--min-train-sessions",
                "126",
                "--training-window-sessions",
                "126",
                "--signal-lookback-sessions",
                "30",
                "--test-sessions",
                "30",
                "--outer-folds",
                "4",
                "--min-oos-sessions",
                "120",
                "--min-fit-observations",
                "126",
                "--model-family",
                "selected_chain",
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid screening configuration", result.stderr)
        self.assertIn("Nested inner fold is infeasible", result.stderr)
        self.assertIn("94 fit observations", result.stderr)
        self.assertIn("131 are required", result.stderr)
        self.assertNotIn("Turso environment variables are unavailable", result.stderr)


if __name__ == "__main__":
    unittest.main()
