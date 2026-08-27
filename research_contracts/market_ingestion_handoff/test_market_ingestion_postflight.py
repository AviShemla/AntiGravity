from __future__ import annotations

import unittest

try:
    from .market_ingestion_postflight import (
        FeatureEvidence,
        PostflightError,
        SnapshotEvidence,
        VisibilityPending,
        reconcile_staging_snapshot,
    )
except ImportError:
    from market_ingestion_postflight import (  # type: ignore
        FeatureEvidence,
        PostflightError,
        SnapshotEvidence,
        VisibilityPending,
        reconcile_staging_snapshot,
    )


class MarketIngestionPostflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.feature_tickers = tuple(f"T{i:03d}" for i in range(474))
        self.snapshot = SnapshotEvidence(
            snapshot_id="market_features_2026-08-26_example",
            status="STAGING",
            expected_rows=587_184,
            expected_tickers=474,
            checksum="a" * 64,
            stored_code_version="b" * 64,
        )
        self.features = FeatureEvidence(
            actual_rows=587_184,
            ticker_rows=self.feature_tickers,
            first_date="2021-09-08",
            last_date="2026-08-26",
        )
        self.lineage = tuple(
            (ticker, "2026-08-26")
            for ticker in sorted(set(self.feature_tickers) | {"^TNX", "^VIX"})
        )

    def reconcile(self, *, lineage=None, features=None, approvals=0, screens=0):
        return reconcile_staging_snapshot(
            snapshot=self.snapshot,
            features=features or self.features,
            lineage_rows=self.lineage if lineage is None else lineage,
            source_session="2026-08-26",
            expected_code_version="b" * 64,
            approval_count=approvals,
            screening_count=screens,
        )

    def test_accepts_474_features_plus_tnx_and_vix(self):
        result = self.reconcile()
        self.assertEqual(474, result["feature_tickers"])
        self.assertEqual(476, result["provider_lineage_rows"])

    def test_missing_lineage_is_visibility_pending(self):
        with self.assertRaisesRegex(VisibilityPending, "missing=.*\\^VIX"):
            self.reconcile(lineage=tuple(row for row in self.lineage if row[0] != "^VIX"))

    def test_extra_lineage_fails_immediately(self):
        with self.assertRaisesRegex(PostflightError, "extra=.*EXTRA"):
            self.reconcile(lineage=self.lineage + (("EXTRA", "2026-08-26"),))

    def test_duplicate_lineage_fails_immediately(self):
        with self.assertRaisesRegex(PostflightError, "duplicate"):
            self.reconcile(lineage=self.lineage + (self.lineage[0],))

    def test_wrong_lineage_session_fails_immediately(self):
        changed = ((self.lineage[0][0], "2026-08-25"),) + self.lineage[1:]
        with self.assertRaisesRegex(PostflightError, "wrong source session"):
            self.reconcile(lineage=changed)

    def test_wrong_feature_session_fails_immediately(self):
        changed = FeatureEvidence(
            actual_rows=self.features.actual_rows,
            ticker_rows=self.features.ticker_rows,
            first_date=self.features.first_date,
            last_date="2026-08-25",
        )
        with self.assertRaisesRegex(PostflightError, "does not end"):
            self.reconcile(features=changed)

    def test_unauthorized_approval_fails_immediately(self):
        with self.assertRaisesRegex(PostflightError, "unauthorized downstream"):
            self.reconcile(approvals=1)

    def test_unauthorized_screening_fails_immediately(self):
        with self.assertRaisesRegex(PostflightError, "unauthorized downstream"):
            self.reconcile(screens=1)


if __name__ == "__main__":
    unittest.main()
