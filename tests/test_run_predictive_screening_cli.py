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
            "--model-family",
        ):
            self.assertIn(argument, result.stderr)
        self.assertIn(
            "--training-window-sessions/--expanding-training-window",
            result.stderr,
        )

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


if __name__ == "__main__":
    unittest.main()
