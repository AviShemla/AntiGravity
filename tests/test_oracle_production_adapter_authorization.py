from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import oracle_production_adapter_authorization as subject
from oracle_production_authorization_envelope import AuthorizationEnvelopeError


class AdapterIntegrationTests(unittest.TestCase):
    def kwargs(self):
        return {
            "envelope": {},
            "authorization": {},
            "expected_envelope_sha256": "a" * 64,
            "application_contract_path": Path("contract.json"),
            "adapter_release_root": Path("releases"),
            "operation_id": "stage:dataset-1",
            "observed_at_utc": datetime(2026, 8, 27, tzinfo=timezone.utc),
        }

    def test_transport_factory_runs_once_and_only_after_gate_passes(self):
        order = []

        def factory():
            order.append("transport")
            return object()

        with mock.patch.object(
            subject,
            "validate_runtime_authorization",
            side_effect=lambda *args, **kwargs: order.append("authorization") or "a" * 64,
        ):
            transport, trusted = subject.authorize_then_create_transport(
                factory, **self.kwargs()
            )
        self.assertIsNotNone(transport)
        self.assertEqual(trusted, "a" * 64)
        self.assertEqual(order, ["authorization", "transport"])

    def test_failed_gate_constructs_no_transport(self):
        calls = []

        def factory():
            calls.append("transport")
            return object()

        with mock.patch.object(
            subject,
            "validate_runtime_authorization",
            side_effect=AuthorizationEnvelopeError("blocked"),
        ):
            with self.assertRaises(AuthorizationEnvelopeError):
                subject.authorize_then_create_transport(factory, **self.kwargs())
        self.assertEqual(calls, [])

    def test_preconstructed_transport_and_none_result_are_rejected(self):
        with self.assertRaises(AuthorizationEnvelopeError):
            subject.authorize_then_create_transport(object(), **self.kwargs())
        with mock.patch.object(
            subject, "validate_runtime_authorization", return_value="a" * 64
        ):
            with self.assertRaises(AuthorizationEnvelopeError):
                subject.authorize_then_create_transport(lambda: None, **self.kwargs())


if __name__ == "__main__":
    unittest.main()
