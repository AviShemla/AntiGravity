from __future__ import annotations

import copy
import unittest
from datetime import datetime, timedelta, timezone

try:
    from .market_ingestion_postflight_cli import build_handoff
    from .verify_postflight_handoff import HandoffVerificationError, verify_handoff
except ImportError:
    from market_ingestion_postflight_cli import build_handoff  # type: ignore
    from verify_postflight_handoff import (  # type: ignore
        HandoffVerificationError,
        verify_handoff,
    )


NOW = datetime(2026, 8, 27, 1, 2, 0, tzinfo=timezone.utc)


class HandoffVerifierTests(unittest.TestCase):
    def setUp(self):
        self.artifact = build_handoff(
            {
                "snapshot_id": "market_features_2026-08-26_example",
                "status": "STAGING",
                "rows": 587_184,
                "feature_tickers": 474,
                "provider_lineage_rows": 476,
                "source_session": "2026-08-26",
                "first_date": "2021-09-08",
                "last_date": "2026-08-26",
                "approval_events": 0,
                "screening_runs": 0,
                "checksum": "a" * 64,
                "code_version": "b" * 64,
            },
            observed_at=(NOW - timedelta(seconds=10)).isoformat(),
        )

    def verify(self, artifact=None):
        return verify_handoff(
            artifact or self.artifact,
            source_session="2026-08-26",
            now=NOW,
            max_age_seconds=300,
        )

    def test_accepts_fresh_hash_bound_staging_handoff(self):
        result = self.verify()
        self.assertEqual("STAGING", result["status"])
        self.assertEqual(10, result["age_seconds"])

    def test_tampered_evidence_fails(self):
        changed = copy.deepcopy(self.artifact)
        changed["evidence"]["rows"] += 1
        with self.assertRaisesRegex(HandoffVerificationError, "hash"):
            self.verify(changed)

    def test_stale_handoff_fails(self):
        changed = build_handoff(
            self.artifact["evidence"],
            observed_at=(NOW - timedelta(seconds=301)).isoformat(),
        )
        with self.assertRaisesRegex(HandoffVerificationError, "stale"):
            self.verify(changed)

    def test_wrong_session_fails(self):
        changed = build_handoff(
            dict(self.artifact["evidence"], source_session="2026-08-25"),
            observed_at=(NOW - timedelta(seconds=10)).isoformat(),
        )
        with self.assertRaisesRegex(HandoffVerificationError, "source session"):
            self.verify(changed)

    def test_unauthorized_downstream_fails(self):
        changed = build_handoff(
            dict(self.artifact["evidence"], screening_runs=1),
            observed_at=(NOW - timedelta(seconds=10)).isoformat(),
        )
        with self.assertRaisesRegex(HandoffVerificationError, "unauthorized"):
            self.verify(changed)

    def test_lineage_count_mismatch_fails(self):
        changed = build_handoff(
            dict(self.artifact["evidence"], provider_lineage_rows=474),
            observed_at=(NOW - timedelta(seconds=10)).isoformat(),
        )
        with self.assertRaisesRegex(HandoffVerificationError, "counts"):
            self.verify(changed)


if __name__ == "__main__":
    unittest.main()
