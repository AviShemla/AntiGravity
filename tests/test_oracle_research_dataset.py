import unittest
from datetime import date, datetime, timezone

from model_lineage import LineageError
from oracle_research_dataset import (
    OracleProviderLineage,
    canonical_provider_lineage_bytes,
    compute_provider_lineage_sha256,
    load_frozen_oracle_research_dataset,
)


SHA_MARKET = "a" * 64
SHA_CONTENT = "b" * 64
SHA_TICKERS = "c" * 64
SHA_EVIDENCE = "e" * 64


def provider_fixture(provider="YAHOO_FINANCE"):
    return OracleProviderLineage(
        ticker="AAA",
        provider=provider,
        requested_source_session_date=date(2026, 8, 25),
        first_available_date=date(2026, 8, 22),
        last_available_date=date(2026, 8, 25),
        source_row_count=4,
        source_checksum_sha256="f" * 64,
    )


SHA_PROVIDER = compute_provider_lineage_sha256((provider_fixture(),))


class Result:
    def __init__(self, columns, rows):
        self.columns = list(columns)
        self.rows = rows


VERSION_COLUMNS = (
    "dataset_version_id", "market_snapshot_id",
    "market_snapshot_checksum_sha256", "source_session_date",
    "evidence_cutoff_utc", "first_session_date", "last_session_date",
    "expected_row_count", "expected_ticker_count", "expected_session_count",
    "expected_provider_lineage_count", "content_sha256",
    "ticker_universe_sha256", "provider_lineage_sha256", "schema_version",
    "code_version", "status", "freeze_approval_id", "frozen_by",
    "frozen_at_utc", "snapshot_dataset_type", "snapshot_source_session_date",
    "snapshot_available_at_utc", "snapshot_checksum_sha256",
    "snapshot_expected_row_count", "snapshot_expected_ticker_count",
    "snapshot_status",
)
EVENT_COLUMNS = (
    "event_id", "event_type", "market_snapshot_checksum_sha256",
    "content_sha256", "ticker_universe_sha256", "provider_lineage_sha256",
    "actor", "decided_at_utc", "evidence_sha256",
)
LINEAGE_COLUMNS = (
    "ticker", "provider", "requested_source_session_date",
    "first_available_date", "last_available_date", "source_row_count",
    "source_checksum_sha256",
)


class FakeDB:
    def __init__(
        self,
        *,
        status="FROZEN",
        snapshot_status="VALIDATED",
        event_type="FREEZE",
        event_content_sha=SHA_CONTENT,
        observed_rows=4,
        actual_provider="YAHOO_FINANCE",
        frozen_at="2026-08-26T07:40:43+00:00",
        provider_lineage_sha=SHA_PROVIDER,
    ):
        self.status = status
        self.snapshot_status = snapshot_status
        self.event_type = event_type
        self.event_content_sha = event_content_sha
        self.observed_rows = observed_rows
        self.actual_provider = actual_provider
        self.frozen_at = frozen_at
        self.provider_lineage_sha = provider_lineage_sha
        self.queries = []

    @staticmethod
    def lineage(provider="YAHOO_FINANCE"):
        return [
            [
                "AAA", provider, "2026-08-25", "2026-08-22", "2026-08-25",
                4, "f" * 64,
            ]
        ]

    def execute(self, query, args):
        compact = " ".join(query.split())
        self.queries.append((compact, list(args)))
        if "FROM oracle_research_dataset_versions d" in compact:
            return Result(
                VERSION_COLUMNS,
                [[
                    "research-1", "market-1", SHA_MARKET, "2026-08-25",
                    "2026-08-26T06:44:37+00:00", "2026-08-22", "2026-08-25",
                    4, 1, 4, 1, SHA_CONTENT, SHA_TICKERS,
                    self.provider_lineage_sha,
                    "oracle-research-v1", "code-1", self.status, "freeze-1",
                    "owner", self.frozen_at, "MARKET_FEATURES", "2026-08-25",
                    "2026-08-26T06:30:00+00:00", SHA_MARKET, 4, 1,
                    self.snapshot_status,
                ]],
            )
        if "FROM oracle_research_dataset_events" in compact:
            return Result(
                EVENT_COLUMNS,
                [[
                    "freeze-1", self.event_type, SHA_MARKET,
                    self.event_content_sha, SHA_TICKERS,
                    self.provider_lineage_sha, "owner",
                    self.frozen_at, SHA_EVIDENCE,
                ]],
            )
        if "COUNT(DISTINCT date) AS session_count" in compact:
            return Result(
                [
                    "row_count", "ticker_count", "session_count",
                    "first_session_date", "last_session_date",
                ],
                [[self.observed_rows, 1, 4, "2026-08-22", "2026-08-25"]],
            )
        if "FROM oracle_research_dataset_provider_lineage" in compact:
            return Result(LINEAGE_COLUMNS, self.lineage())
        if "FROM market_data_provider_lineage" in compact:
            return Result(LINEAGE_COLUMNS, self.lineage(self.actual_provider))
        raise AssertionError(f"Unexpected query: {compact}")


def load(db, **overrides):
    arguments = {
        "dataset_version_id": "research-1",
        "expected_market_snapshot_id": "market-1",
        "expected_market_snapshot_checksum_sha256": SHA_MARKET,
        "expected_source_session_date": date(2026, 8, 25),
        "cutoff_utc": datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc),
    }
    arguments.update(overrides)
    return load_frozen_oracle_research_dataset(db, **arguments)


class OracleResearchDatasetTests(unittest.TestCase):
    def test_exact_frozen_dataset_and_provider_readback_pass(self):
        db = FakeDB()
        dataset = load(db)
        self.assertEqual(dataset.dataset_version_id, "research-1")
        self.assertEqual(dataset.market_snapshot_id, "market-1")
        self.assertEqual(dataset.expected_row_count, 4)
        self.assertEqual(dataset.expected_ticker_count, 1)
        self.assertEqual(dataset.expected_session_count, 4)
        self.assertEqual(dataset.provider_lineage[0].provider, "YAHOO_FINANCE")
        self.assertTrue(all("INSERT " not in query.upper() for query, _ in db.queries))

    def test_non_frozen_dataset_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "not FROZEN"):
            load(FakeDB(status="STAGING"))

    def test_non_validated_market_snapshot_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "not VALIDATED"):
            load(FakeDB(snapshot_status="STAGING"))

    def test_expected_snapshot_identity_and_checksum_are_mandatory(self):
        with self.assertRaisesRegex(LineageError, "different market snapshot ID"):
            load(FakeDB(), expected_market_snapshot_id="market-other")
        with self.assertRaisesRegex(LineageError, "does not match"):
            load(
                FakeDB(),
                expected_market_snapshot_checksum_sha256="9" * 64,
            )

    def test_latest_revocation_event_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "not FREEZE"):
            load(FakeDB(event_type="REVOKE"))

    def test_freeze_event_checksum_drift_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "checksums do not match"):
            load(FakeDB(event_content_sha="0" * 64))

    def test_market_count_drift_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "coverage has drifted"):
            load(FakeDB(observed_rows=3))

    def test_provider_lineage_drift_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "provider lineage has drifted"):
            load(FakeDB(actual_provider="TIINGO_EOD"))

    def test_provider_lineage_digest_is_recomputed_and_mismatch_fails_closed(self):
        expected_bytes = (
            '["AAA","YAHOO_FINANCE","2026-08-25","2026-08-22",'
            '"2026-08-25",4,"' + "f" * 64 + '"]\n'
        ).encode("utf-8")
        self.assertEqual(canonical_provider_lineage_bytes((provider_fixture(),)), expected_bytes)
        with self.assertRaisesRegex(LineageError, "digest does not match"):
            load(FakeDB(provider_lineage_sha="0" * 64))

    def test_future_freeze_and_naive_cutoff_fail_closed(self):
        with self.assertRaisesRegex(LineageError, "chronology"):
            load(FakeDB(frozen_at="2026-08-26T09:00:00+00:00"))
        with self.assertRaisesRegex(LineageError, "timezone-aware"):
            load(
                FakeDB(),
                cutoff_utc=datetime(2026, 8, 26, 8, 0),
            )


if __name__ == "__main__":
    unittest.main()
