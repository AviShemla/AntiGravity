import unittest
from dataclasses import replace

from execution_lineage import ExecutionAction, ExecutionEvent, save_execution_event
from model_lineage import LineageError


HASH_A = "a" * 64
HASH_B = "b" * 64


class Writer:
    def __init__(self):
        self.calls = []

    def execute_write(self, query, args):
        self.calls.append((query, args))


def buy_event():
    return ExecutionEvent(
        event_id="event-1",
        plan_id="plan-1",
        sequence_number=1,
        persona="Neutral",
        target_date="2026-08-24",
        ticker="AAA",
        action=ExecutionAction.BUY,
        units=10.0,
        reference_price=100.0,
        execution_price=100.0,
        fees=1.0,
        cash_delta=-1001.0,
        holdings_value_delta=1000.0,
        realized_pnl=None,
        reference_quote_timestamp_utc="2026-08-24T13:30:01+00:00",
        before_state_sha256=HASH_A,
        after_state_sha256=HASH_B,
        previous_event_sha256=None,
        decision_evidence={"quote_id": "quote-1"},
        created_at_utc="2026-08-24T13:30:02+00:00",
    )


class ExecutionLineageTests(unittest.TestCase):
    def test_valid_buy_is_hashed_and_appended(self):
        writer = Writer()
        digest = save_execution_event(writer, buy_event())
        self.assertEqual(len(digest), 64)
        self.assertEqual(len(writer.calls), 1)
        self.assertIn("INSERT INTO execution_events", writer.calls[0][0])
        self.assertEqual(writer.calls[0][1][18], digest)

    def test_bad_buy_sign_is_rejected(self):
        with self.assertRaisesRegex(LineageError, "invalid signs"):
            replace(buy_event(), cash_delta=1001.0).validate()

    def test_unbalanced_trade_is_rejected(self):
        with self.assertRaisesRegex(LineageError, "do not reconcile"):
            replace(buy_event(), cash_delta=-900.0).validate()

    def test_sell_requires_realized_pnl(self):
        event = replace(
            buy_event(),
            action=ExecutionAction.SELL,
            cash_delta=999.0,
            holdings_value_delta=-1000.0,
        )
        with self.assertRaisesRegex(LineageError, "realized PnL"):
            event.validate()

    def test_non_trade_cannot_move_money(self):
        event = replace(
            buy_event(),
            action=ExecutionAction.KILL_SWITCH,
            ticker=None,
            units=None,
            reference_price=None,
            execution_price=None,
            fees=0.0,
            cash_delta=-1.0,
            holdings_value_delta=1.0,
            reference_quote_timestamp_utc=None,
        )
        with self.assertRaisesRegex(LineageError, "cannot change"):
            event.validate()


if __name__ == "__main__":
    unittest.main()
