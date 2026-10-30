from __future__ import annotations

import copy
import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import mock_open, patch

try:
    from migration_plan_validation_impl.migration_plan_validator import (
        CONTRACT_VERSION,
        FORBIDDEN_AUTOMATIC_CAPABILITIES,
        PlanValidationError,
        TARGET_ARCHITECTURE,
        assert_valid_plan,
        main,
        validate_plan,
        validation_report,
    )
except ModuleNotFoundError:  # Direct discovery from this directory.
    from migration_plan_validator import (  # type: ignore
        CONTRACT_VERSION,
        FORBIDDEN_AUTOMATIC_CAPABILITIES,
        PlanValidationError,
        TARGET_ARCHITECTURE,
        assert_valid_plan,
        main,
        validate_plan,
        validation_report,
    )


def action(action_id: str, capability: str = "READ_ONLY_INSPECTION") -> dict:
    return {
        "id": action_id,
        "capability": capability,
        "description": f"perform {action_id}",
        "automatic": True,
        "approval_ref": None,
    }


def stage(
    stage_id: str,
    *,
    owner: str,
    dependencies: list[str],
    on_success: str | None,
    evidence_stage: str = "TESTED",
) -> dict:
    test_satisfied = evidence_stage in {"TESTED", "DEPLOYED", "OBSERVED", "VERIFIED"}
    observe_satisfied = evidence_stage in {"OBSERVED", "VERIFIED"}
    readback_satisfied = evidence_stage == "VERIFIED"
    return {
        "id": stage_id,
        "title": f"Stage {stage_id}",
        "owner": owner,
        "action_class": "SAFE_NOW",
        "evidence_stage": evidence_stage,
        "dependencies": dependencies,
        "progress": {"numerator": 1, "denominator": 2, "unit": "gates"},
        "data_sources": [{"kind": "TURSO", "scope": "RESEARCH"}],
        "filesystem_boundary": {
            "allowed_write_roots": [f"/var/lib/codex-oracle/{stage_id}"],
            "resolved_targets_verified": True,
            "broad_recursive_actions_forbidden": True,
        },
        "operations": [action(f"{stage_id}-inspect")],
        "evidence_gates": {
            "test": {
                "required": True,
                "satisfied": test_satisfied,
                "evidence_refs": [f"evidence://{stage_id}/test"] if test_satisfied else [],
            },
            "observe": {
                "required": True,
                "satisfied": observe_satisfied,
                "evidence_refs": [f"evidence://{stage_id}/observe"] if observe_satisfied else [],
            },
            "readback": {
                "required": True,
                "satisfied": readback_satisfied,
                "evidence_refs": [f"evidence://{stage_id}/readback"] if readback_satisfied else [],
            },
        },
        "autofix": {
            "enabled": True,
            "reversible": True,
            "idempotent": True,
            "max_attempts": 1,
            "preconditions": ["evidence preserved", "no duplicate writer"],
            "actions": [action(f"{stage_id}-repair", "REVERSIBLE_CODE_REPAIR")],
            "post_fix_tests": ["focused tests", "independent readback"],
        },
        "rollback": {
            "trigger": "post-fix test fails",
            "actions": [action(f"{stage_id}-rollback", "REVERSIBLE_ROLLBACK")],
            "verification": ["artifact identity restored"],
            "data_loss_allowed": False,
        },
        "liveness": {
            "max_checkpoint_age_seconds": 900,
            "progress_marker": f"/var/lib/codex-oracle/{stage_id}/checkpoint.json",
            "stalled_state": "STALLED",
            "preserve_evidence": True,
            "prevent_duplicate_retry": True,
            "resume_from_checkpoint": True,
            "actions": [action(f"{stage_id}-resume", "IDEMPOTENT_RESUME")],
        },
        "successors": {
            "on_success": on_success,
            "on_failure": stage_id,
            "on_stalled": stage_id,
        },
        "successor_gates": {
            "on_success": {
                "condition": "independent completion audit passes",
                "required_evidence": ["terminal state", "exact reconciliation"],
                "safety_checks": [
                    "evidence_preserved",
                    "no_duplicate_writer",
                    "safety_invariants_hold",
                    "completion_independently_read_back",
                ],
            },
            "on_failure": {
                "condition": "failure evidence is durable",
                "required_evidence": ["terminal failure state", "journal"],
                "safety_checks": [
                    "evidence_preserved",
                    "no_duplicate_writer",
                    "safety_invariants_hold",
                ],
            },
            "on_stalled": {
                "condition": "checkpoint exceeds declared maximum age",
                "required_evidence": ["live process identity", "checkpoint age"],
                "safety_checks": [
                    "evidence_preserved",
                    "no_duplicate_writer",
                    "safety_invariants_hold",
                ],
            },
        },
    }


def valid_plan() -> dict:
    plan = {
        "contract_version": CONTRACT_VERSION,
        "plan_id": "oracle-migration-20260827",
        "target_architecture": TARGET_ARCHITECTURE,
        "safety": {
            "production_source_of_truth": "TURSO",
            "forbidden_production_sources": ["CSV", "EXCEL", "SQLITE", "STREAMLIT"],
            "forbidden_automatic_capabilities": sorted(FORBIDDEN_AUTOMATIC_CAPABILITIES),
            "approval_required_capabilities": sorted(FORBIDDEN_AUTOMATIC_CAPABILITIES),
            "hard_gates_not_waivable": True,
            "service_invariants": [
                {"name": "ag-sniper.service", "active_state": "inactive", "enabled": False},
                {"name": "antigravity-nightly.timer", "active_state": "inactive", "enabled": False},
                {"name": "antigravity-qa-watchdog.timer", "active_state": "inactive", "enabled": False},
            ],
        },
        "stages": [
            stage("audit", owner="audit-owner", dependencies=[], on_success="freeze"),
            stage(
                "freeze",
                owner="freeze-owner",
                dependencies=["audit"],
                on_success=None,
                evidence_stage="VERIFIED",
            ),
        ],
        "successor_ownership": {
            "audit": "audit-owner",
            "freeze": "freeze-owner",
        },
    }
    return plan


def issue_codes(plan: dict) -> set[str]:
    return {issue.code for issue in validate_plan(plan)}


class ValidPlanTests(unittest.TestCase):
    def test_valid_plan_has_no_issues(self) -> None:
        self.assertEqual((), validate_plan(valid_plan()))

    def test_assert_valid_plan_accepts_valid_plan(self) -> None:
        self.assertIsNone(assert_valid_plan(valid_plan()))

    def test_isolated_fixture_is_allowed_only_for_test_scope(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["data_sources"] = [
            {"kind": "ISOLATED_FIXTURE", "scope": "ISOLATED_TEST"}
        ]
        self.assertEqual((), validate_plan(plan))

    def test_validation_report_is_machine_readable(self) -> None:
        report = validation_report(valid_plan())
        self.assertTrue(report["valid"])
        self.assertEqual(0, report["issue_count"])
        json.dumps(report)


class CliTests(unittest.TestCase):
    def _invoke(self, content: str) -> tuple[int, dict]:
        # Mock the read boundary: the managed test environment intentionally
        # denies some host temp paths, and the CLI itself must remain read-only.
        output = StringIO()
        with patch("pathlib.Path.open", mock_open(read_data=content)):
            with redirect_stdout(output):
                exit_code = main(["plan.json"])
        return exit_code, json.loads(output.getvalue())

    def test_cli_accepts_valid_json_plan(self) -> None:
        exit_code, report = self._invoke(json.dumps(valid_plan()))
        self.assertEqual(0, exit_code)
        self.assertTrue(report["valid"])

    def test_cli_rejects_invalid_plan_with_exit_two(self) -> None:
        plan = valid_plan()
        plan["target_architecture"] = "legacy"
        exit_code, report = self._invoke(json.dumps(plan))
        self.assertEqual(2, exit_code)
        self.assertFalse(report["valid"])
        self.assertEqual("TARGET", report["issues"][0]["code"])

    def test_cli_fails_closed_on_malformed_json_without_echoing_content(self) -> None:
        secret_marker = "do-not-echo-this"
        exit_code, report = self._invoke("{" + secret_marker)
        self.assertEqual(2, exit_code)
        self.assertFalse(report["valid"])
        serialized = json.dumps(report)
        self.assertNotIn(secret_marker, serialized)
        self.assertEqual("PLAN_READ_FAILED", report["issues"][0]["code"])


class ContractAndGraphTests(unittest.TestCase):
    def test_missing_required_top_level_field(self) -> None:
        plan = valid_plan()
        del plan["safety"]
        self.assertIn("REQUIRED", issue_codes(plan))

    def test_contract_and_target_are_exact(self) -> None:
        plan = valid_plan()
        plan["contract_version"] = "v0"
        plan["target_architecture"] = "ANTIGRAVITY"
        self.assertTrue({"CONTRACT", "TARGET"}.issubset(issue_codes(plan)))

    def test_duplicate_stage_id_is_rejected(self) -> None:
        plan = valid_plan()
        plan["stages"][1]["id"] = "audit"
        self.assertIn("DUPLICATE", issue_codes(plan))

    def test_unknown_dependency_and_successor_are_rejected(self) -> None:
        plan = valid_plan()
        plan["stages"][1]["dependencies"] = ["missing"]
        plan["stages"][0]["successors"]["on_success"] = "also-missing"
        self.assertIn("UNKNOWN_STAGE", issue_codes(plan))

    def test_dependency_cycle_is_rejected(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["dependencies"] = ["freeze"]
        self.assertIn("DEPENDENCY_CYCLE", issue_codes(plan))

    def test_self_dependency_is_rejected(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["dependencies"] = ["audit"]
        self.assertIn("SELF_DEPENDENCY", issue_codes(plan))

    def test_successor_ownership_must_cover_exact_targets(self) -> None:
        plan = valid_plan()
        del plan["successor_ownership"]["freeze"]
        self.assertIn("OWNERSHIP_COVERAGE", issue_codes(plan))

    def test_successor_owner_must_match_stage_owner(self) -> None:
        plan = valid_plan()
        plan["successor_ownership"]["freeze"] = "somebody-else"
        self.assertIn("OWNER_MISMATCH", issue_codes(plan))


class EvidenceAndProgressTests(unittest.TestCase):
    def test_evidence_stage_enum_is_strict(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["evidence_stage"] = "COMPLETE"
        self.assertIn("ENUM", issue_codes(plan))

    def test_tested_requires_test_gate_evidence(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["evidence_gates"]["test"]["satisfied"] = False
        plan["stages"][0]["evidence_gates"]["test"]["evidence_refs"] = []
        self.assertIn("EVIDENCE_STAGE_CONTRADICTION", issue_codes(plan))

    def test_observed_requires_observe_gate(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["evidence_stage"] = "OBSERVED"
        self.assertIn("EVIDENCE_STAGE_CONTRADICTION", issue_codes(plan))

    def test_verified_requires_readback_gate(self) -> None:
        plan = valid_plan()
        plan["stages"][1]["evidence_gates"]["readback"]["satisfied"] = False
        plan["stages"][1]["evidence_gates"]["readback"]["evidence_refs"] = []
        self.assertIn("EVIDENCE_STAGE_CONTRADICTION", issue_codes(plan))

    def test_satisfied_gate_requires_evidence_reference(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["evidence_gates"]["test"]["evidence_refs"] = []
        self.assertIn("EVIDENCE_MISSING", issue_codes(plan))

    def test_evidence_gate_cannot_be_optional(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["evidence_gates"]["readback"]["required"] = False
        self.assertIn("GATE_WEAKENED", issue_codes(plan))

    def test_progress_requires_explicit_integer_fraction(self) -> None:
        plan = valid_plan()
        del plan["stages"][0]["progress"]["denominator"]
        self.assertIn("REQUIRED", issue_codes(plan))

    def test_progress_range_is_enforced(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["progress"] = {"numerator": 2, "denominator": 1, "unit": "gates"}
        self.assertIn("RANGE", issue_codes(plan))


class SafetyAndSourceTests(unittest.TestCase):
    def test_turso_is_exact_production_source(self) -> None:
        plan = valid_plan()
        plan["safety"]["production_source_of_truth"] = "SQLITE"
        self.assertIn("TURSO_REQUIRED", issue_codes(plan))

    def test_forbidden_production_source_set_is_exact(self) -> None:
        plan = valid_plan()
        plan["safety"]["forbidden_production_sources"].remove("CSV")
        self.assertIn("EXACT_SET", issue_codes(plan))

    def test_non_turso_research_source_is_rejected(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["data_sources"] = [{"kind": "CSV", "scope": "RESEARCH"}]
        self.assertTrue({"SOURCE_FORBIDDEN", "TURSO_REQUIRED"}.issubset(issue_codes(plan)))

    def test_fixture_cannot_be_production_source(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["data_sources"] = [
            {"kind": "ISOLATED_FIXTURE", "scope": "PRODUCTION"}
        ]
        self.assertTrue({"TURSO_REQUIRED", "FIXTURE_SCOPE"}.issubset(issue_codes(plan)))

    def test_filesystem_boundary_requires_explicit_write_roots(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["filesystem_boundary"]["allowed_write_roots"] = []
        self.assertIn("TYPE", issue_codes(plan))

    def test_filesystem_targets_must_be_resolved_and_broad_recursion_forbidden(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["filesystem_boundary"]["resolved_targets_verified"] = False
        plan["stages"][0]["filesystem_boundary"]["broad_recursive_actions_forbidden"] = False
        self.assertIn("REQUIRED_TRUE", issue_codes(plan))

    def test_every_forbidden_capability_must_be_in_safety_sets(self) -> None:
        plan = valid_plan()
        plan["safety"]["forbidden_automatic_capabilities"].remove("TRADING")
        plan["safety"]["approval_required_capabilities"].remove("TRADING")
        self.assertTrue({"EXACT_SET", "APPROVAL_SET"}.issubset(issue_codes(plan)))

    def test_hard_gates_cannot_be_waivable(self) -> None:
        plan = valid_plan()
        plan["safety"]["hard_gates_not_waivable"] = False
        self.assertIn("REQUIRED_TRUE", issue_codes(plan))

    def test_required_services_are_exact(self) -> None:
        plan = valid_plan()
        plan["safety"]["service_invariants"].pop()
        self.assertIn("EXACT_SERVICES", issue_codes(plan))

    def test_required_services_must_be_inactive_and_disabled(self) -> None:
        plan = valid_plan()
        plan["safety"]["service_invariants"][0]["active_state"] = "active"
        plan["safety"]["service_invariants"][0]["enabled"] = True
        self.assertIn("SAFETY_STATE", issue_codes(plan))

    def test_unsafe_capability_cannot_be_automatic(self) -> None:
        for capability in FORBIDDEN_AUTOMATIC_CAPABILITIES:
            with self.subTest(capability=capability):
                plan = valid_plan()
                bad = action("unsafe", capability)
                bad["approval_ref"] = "approval://scoped"
                plan["stages"][0]["operations"] = [bad]
                self.assertIn("UNSAFE_AUTOMATION", issue_codes(plan))

    def test_unsafe_manual_action_needs_approval_reference(self) -> None:
        plan = valid_plan()
        bad = action("manual-schema", "PRODUCTION_SCHEMA_APPLICATION")
        bad["automatic"] = False
        bad["approval_ref"] = None
        plan["stages"][0]["action_class"] = "APPROVAL_REQUIRED"
        plan["stages"][0]["operations"] = [bad]
        self.assertIn("APPROVAL_REQUIRED", issue_codes(plan))

    def test_unsafe_manual_action_with_approval_reference_is_structurally_valid(self) -> None:
        plan = valid_plan()
        manual = action("manual-schema", "PRODUCTION_SCHEMA_APPLICATION")
        manual["automatic"] = False
        manual["approval_ref"] = "approval://avi/scope/production-schema"
        plan["stages"][0]["action_class"] = "APPROVAL_REQUIRED"
        plan["stages"][0]["operations"] = [manual]
        self.assertEqual((), validate_plan(plan))


class RecoveryAndRollbackTests(unittest.TestCase):
    def test_autofix_must_be_reversible_and_idempotent(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["autofix"]["reversible"] = False
        plan["stages"][0]["autofix"]["idempotent"] = False
        self.assertIn("REQUIRED_TRUE", issue_codes(plan))

    def test_autofix_requires_bounded_attempts_and_post_tests(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["autofix"]["max_attempts"] = 0
        plan["stages"][0]["autofix"]["post_fix_tests"] = []
        self.assertTrue({"RANGE", "TYPE"}.issubset(issue_codes(plan)))

    def test_rollback_cannot_allow_data_loss(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["rollback"]["data_loss_allowed"] = True
        self.assertIn("REQUIRED_FALSE", issue_codes(plan))

    def test_recovery_requires_stalled_classification(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["liveness"]["stalled_state"] = "WAITING"
        self.assertIn("ENUM", issue_codes(plan))

    def test_recovery_requires_positive_checkpoint_age(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["liveness"]["max_checkpoint_age_seconds"] = 0
        self.assertIn("RANGE", issue_codes(plan))

    def test_recovery_requires_preservation_deduplication_and_resume(self) -> None:
        plan = valid_plan()
        for key in ("preserve_evidence", "prevent_duplicate_retry", "resume_from_checkpoint"):
            plan["stages"][0]["liveness"][key] = False
        self.assertIn("REQUIRED_TRUE", issue_codes(plan))

    def test_successor_gate_is_required_for_every_transition(self) -> None:
        plan = valid_plan()
        del plan["stages"][0]["successor_gates"]["on_failure"]
        self.assertIn("REQUIRED", issue_codes(plan))

    def test_success_transition_requires_independent_readback(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["successor_gates"]["on_success"]["safety_checks"].remove(
            "completion_independently_read_back"
        )
        self.assertIn("SUCCESSOR_GATE_WEAKENED", issue_codes(plan))

    def test_every_successor_transition_preserves_evidence_and_safety(self) -> None:
        plan = valid_plan()
        plan["stages"][0]["successor_gates"]["on_stalled"]["safety_checks"] = []
        self.assertIn("SUCCESSOR_GATE_WEAKENED", issue_codes(plan))

    def test_unsafe_action_is_rejected_inside_autofix_even_if_marked_manual(self) -> None:
        plan = valid_plan()
        bad = action("bad-autofix", "SNAPSHOT_PROMOTION")
        bad["automatic"] = False
        bad["approval_ref"] = "approval://should-not-matter"
        plan["stages"][0]["autofix"]["actions"] = [bad]
        self.assertIn("UNSAFE_AUTOMATION", issue_codes(plan))

    def test_unsafe_action_is_rejected_inside_rollback(self) -> None:
        plan = valid_plan()
        bad = action("bad-rollback", "ORDER_CREATION")
        bad["automatic"] = False
        bad["approval_ref"] = "approval://should-not-matter"
        plan["stages"][0]["rollback"]["actions"] = [bad]
        self.assertIn("UNSAFE_AUTOMATION", issue_codes(plan))

    def test_invalid_plan_exception_preserves_issues(self) -> None:
        plan = copy.deepcopy(valid_plan())
        plan["stages"][0]["progress"]["denominator"] = 0
        with self.assertRaises(PlanValidationError) as raised:
            assert_valid_plan(plan)
        self.assertTrue(raised.exception.issues)
        self.assertIn("invalid Codex Oracle migration plan", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
