import unittest
from dataclasses import replace
from datetime import date

from execution_preflight import (
    PendingOrder,
    PlanEvidence,
    pending_payload_sha256,
    validate_execution_preflight,
)


PERSONA = "Neutral"
SOURCE = date(2026, 8, 21)
TARGET = date(2026, 8, 24)


def order():
    return PendingOrder(
        persona=PERSONA,
        target_date=TARGET.isoformat(),
        target_cash=9000.0,
        target_total_equity=10000.0,
        target_holdings={"AAA": {"dollars": 1000.0, "units": 10, "price": 100.0}},
        daily_pnl={},
        executed_intraday_trades={},
    )


def evidence(pending):
    return PlanEvidence(
        plan_id="plan-1",
        persona=PERSONA,
        asset_class="STOCK",
        target_date=TARGET.isoformat(),
        source_session_date=SOURCE.isoformat(),
        market_snapshot_id="snapshot-1",
        snapshot_status="VALIDATED",
        snapshot_source_session_date=SOURCE.isoformat(),
        model_run_id="run-1",
        model_run_status="COMPLETED",
        model_prediction_date=TARGET.isoformat(),
        model_source_session_date=SOURCE.isoformat(),
        pending_payload_sha256=pending_payload_sha256(pending),
        qa_status="VALIDATED",
        approval_decision="APPROVED",
        approved_by="AviShemla",
        consumed_plan_id=None,
    )


class ExecutionPreflightTests(unittest.TestCase):
    def validate(self, pending, plan):
        return validate_execution_preflight(
            [pending],
            [plan],
            expected_personas={PERSONA},
            expected_source_session=SOURCE,
            expected_target_date=TARGET,
            expected_approver="AviShemla",
            latest_ledger_dates={PERSONA: SOURCE.isoformat()},
        )

    def test_valid_exact_plan_passes(self):
        pending = order()
        report = self.validate(pending, evidence(pending))
        self.assertTrue(report.passed)
        self.assertEqual(report.failures, ())

    def test_payload_substitution_is_rejected(self):
        pending = order()
        plan = evidence(pending)
        changed = replace(pending, target_cash=8999.0, target_total_equity=9999.0)
        report = self.validate(changed, plan)
        self.assertFalse(report.passed)
        self.assertIn(f"{PERSONA}: pending payload checksum mismatch.", report.failures)

    def test_unapproved_plan_is_rejected(self):
        pending = order()
        plan = replace(evidence(pending), approval_decision=None, approved_by=None)
        report = self.validate(pending, plan)
        self.assertFalse(report.passed)
        self.assertIn(f"{PERSONA}: execution plan is not approved.", report.failures)

    def test_stale_source_session_is_rejected(self):
        pending = order()
        plan = replace(evidence(pending), source_session_date="2026-08-20")
        report = self.validate(pending, plan)
        self.assertFalse(report.passed)
        self.assertIn(f"{PERSONA}: execution-plan source session mismatch.", report.failures)

    def test_consumed_plan_is_rejected(self):
        pending = order()
        plan = replace(evidence(pending), consumed_plan_id="plan-1")
        report = self.validate(pending, plan)
        self.assertFalse(report.passed)
        self.assertIn(f"{PERSONA}: execution plan was already consumed.", report.failures)

    def test_bad_double_entry_is_rejected(self):
        pending = replace(order(), target_total_equity=9990.0)
        report = self.validate(pending, evidence(pending))
        self.assertFalse(report.passed)
        self.assertIn(
            f"{PERSONA}: Target equity does not equal cash plus holdings.",
            report.failures,
        )

    def test_existing_intraday_execution_is_rejected(self):
        pending = replace(order(), executed_intraday_trades={"AAA": {"type": "BUY"}})
        report = self.validate(pending, evidence(pending))
        self.assertFalse(report.passed)
        self.assertIn(
            f"{PERSONA}: Proposed plan already contains intraday executions.",
            report.failures,
        )

    def test_incomplete_persona_coverage_is_rejected(self):
        pending = order()
        report = validate_execution_preflight(
            [pending],
            [evidence(pending)],
            expected_personas={PERSONA, "Conservative"},
            expected_source_session=SOURCE,
            expected_target_date=TARGET,
            expected_approver="AviShemla",
            latest_ledger_dates={
                PERSONA: SOURCE.isoformat(),
                "Conservative": SOURCE.isoformat(),
            },
        )
        self.assertFalse(report.passed)
        self.assertIn("Pending-order persona coverage is not exact.", report.failures)
        self.assertIn("Execution-plan persona coverage is not exact.", report.failures)

    def test_stale_ledger_is_rejected(self):
        pending = order()
        report = validate_execution_preflight(
            [pending],
            [evidence(pending)],
            expected_personas={PERSONA},
            expected_source_session=SOURCE,
            expected_target_date=TARGET,
            expected_approver="AviShemla",
            latest_ledger_dates={PERSONA: "2026-08-20"},
        )
        self.assertFalse(report.passed)
        self.assertIn(
            f"{PERSONA}: latest ledger date does not match source session.",
            report.failures,
        )


if __name__ == "__main__":
    unittest.main()
