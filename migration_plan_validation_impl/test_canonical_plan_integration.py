"""Cross-artifact and incident-fault checks for the canonical migration plan."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from .migration_plan_validator import validate_plan


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_PATH = ROOT / "migration_plan_impl" / "CODEX_ORACLE_MIGRATION_PLAN.md"
REGISTRY_PATH = ROOT / "migration_plan_impl" / "CODEX_ORACLE_STAGE_REGISTRY.json"


class CanonicalPlanIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.markdown = MARKDOWN_PATH.read_text(encoding="utf-8")
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.by_stage = {stage["id"]: stage for stage in cls.registry["stages"]}

    def test_registry_passes_strict_validator(self) -> None:
        self.assertEqual(validate_plan(self.registry), ())

    def test_stage_set_is_finite_and_exact(self) -> None:
        self.assertEqual(set(self.by_stage), {f"S{index:02d}" for index in range(17)})

    def test_markdown_contains_every_registry_stage(self) -> None:
        for stage_id, stage in self.by_stage.items():
            self.assertIn(f"### {stage_id} —", self.markdown)
            self.assertIn(stage["name"], self.markdown)

    def test_eight_workstream_denominators_are_fixed(self) -> None:
        expected = {"W1": 1, "W2": 1, "W3": 1, "W4": 3, "W5": 4,
                    "W6": 5, "W7": 474, "W8": 1}
        actual = {
            item["id"]: item["denominator"]
            for item in self.registry["fixed_workstreams"]
        }
        self.assertEqual(actual, expected)

    def test_ingestion_false_red_is_bound_to_exact_contract(self) -> None:
        for token in (
            "market_features_2026-08-26_911350a3784e5b1d",
            "587,184",
            "474 feature tickers",
            "476 provider-lineage",
            "^TNX",
            "^VIX",
        ):
            self.assertIn(token, self.markdown)

    def test_baseline_failure_and_verified_successor_are_exact(self) -> None:
        for token in (
            "d19062f22c4b4be1ba39424e8aed2c8a",
            "/v2/pipeline",
            "a1323c841529468abfb1b66078181700",
            "46ea3bf6e8526f802de4d39000c8201c091fbb2cf1c2f33e5dce8381701ebaff",
            "54746936464af077886908bf818b7e0703c06685997ac501167b755470ad4a7e",
        ):
            self.assertIn(token, self.markdown)

    def test_current_preregistration_commit_and_test_scope_are_recorded(self) -> None:
        stage = self.by_stage["S07"]
        self.assertEqual(stage["progress"], {
            "numerator": 3,
            "denominator": 5,
            "unit": "preregistration runtime evidence gates",
        })
        self.assertIn("af5cb30c8b4ed3d19a90c0151ec20b30edff4761", self.markdown)
        self.assertIn("69/69", self.markdown)

    def test_fault_model_covers_required_incidents(self) -> None:
        normalized = self.markdown.lower()
        for phrase in (
            "false-red",
            "delayed turso visibility",
            "duplicate run",
            "stale checkpoint",
            "wrong checksum",
            "provider fallback",
            "no qualifying model output",
            "resource contention",
        ):
            self.assertIn(phrase, normalized)

    def test_single_successor_ownership_is_explicit(self) -> None:
        self.assertIn("One writer per idempotency key", self.markdown)
        self.assertEqual(
            set(self.registry["successor_ownership"]),
            {
                target
                for stage in self.registry["stages"]
                for target in stage["successors"].values()
                if target is not None
            },
        )

    def test_nightly_continuity_is_temporary_and_finally_retired(self) -> None:
        self.assertIn("Temporary guarded nightly continuity", self.by_stage["S02"]["name"])
        final_text = " ".join(self.by_stage["S16"]["actions"]).lower()
        self.assertIn("retire temporary nightly", final_text)
        self.assertIn("update drive checkpoint", final_text)

    def test_model_fit_requires_separate_authorization(self) -> None:
        stage_text = json.dumps(self.by_stage["S07"], sort_keys=True).lower()
        self.assertIn("separate fit-authorization", stage_text)
        self.assertIn("fit only when separate authorization is true", stage_text)

    def test_trading_is_not_an_automatic_successor(self) -> None:
        self.assertIn("Live trading is not an automatic successor", self.markdown)
        self.assertIn("paper/shadow", self.markdown)

    def test_every_stage_has_filesystem_and_liveness_boundaries(self) -> None:
        for stage in self.registry["stages"]:
            self.assertTrue(stage["filesystem_boundary"]["allowed_write_roots"])
            self.assertGreater(stage["liveness"]["max_checkpoint_age_seconds"], 0)
            self.assertEqual(stage["liveness"]["stalled_state"], "STALLED")

    def test_completion_requires_independent_readback_not_shell_exit(self) -> None:
        self.assertIn("Passing unit tests, a zero shell exit", self.markdown)
        for stage in self.registry["stages"]:
            self.assertTrue(stage["evidence_gates"]["readback"]["required"])

    def test_plan_is_not_claimed_complete(self) -> None:
        self.assertIn("Plan status: `CANONICAL_BASELINE`", self.markdown)
        self.assertEqual(self.registry["plan_status"], "CANONICAL_BASELINE")
        self.assertNotIn("MIGRATION_COMPLETE", self.markdown)


if __name__ == "__main__":
    unittest.main()
