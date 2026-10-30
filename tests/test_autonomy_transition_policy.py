from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.validate_autonomy_transition_policy import validate_policy

POLICY_PATH = Path("governance/autonomy_transition_policy.json")


class AutonomyTransitionPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    def test_repository_policy_passes(self) -> None:
        self.assertEqual(validate_policy(self.policy), [])

    def test_missing_failure_trigger_fails_closed(self) -> None:
        altered = copy.deepcopy(self.policy)
        altered["trigger_states"].remove("NO_QUALIFYING_OUTPUT")
        self.assertIn(
            "trigger_states must contain the complete governed set",
            validate_policy(altered),
        )

    def test_safe_successor_launch_cannot_be_disabled(self) -> None:
        altered = copy.deepcopy(self.policy)
        altered["requirements"]["launch_all_independent_safe_now"] = False
        self.assertIn(
            "requirement launch_all_independent_safe_now must be true",
            validate_policy(altered),
        )

    def test_safety_gate_preservation_cannot_be_disabled(self) -> None:
        altered = copy.deepcopy(self.policy)
        altered["requirements"]["preserve_safety_gates"] = False
        self.assertIn(
            "requirement preserve_safety_gates must be true",
            validate_policy(altered),
        )


if __name__ == "__main__":
    unittest.main()
