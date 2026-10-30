from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
import hashlib
import struct
import unittest

from oracle_research_dataset_serializers import (
    MARKET_DAILY_FEATURE_COLUMNS,
    MarketDatasetStreamingDigester,
)

from .s08_signal_panel_materializer import (
    FLOAT_CONTRACT, SIGNAL_CONTRACT, FrozenMarketBinding, S07SignalBinding,
    ImportedSerializerBinding, TrustedReadbackBinding, SignalPanelError,
    binding_artifact_sha256, canonical_session_dates_sha256,
    canonical_ticker_list_sha256, materialize_signal_panel,
    trusted_readback_artifact_sha256,
)


def weekdays(start: date, count: int) -> tuple[str, ...]:
    values = []
    current = start
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current.isoformat())
        current += timedelta(days=1)
    return tuple(values)


class SignalPanelMaterializerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tickers = tuple(f"T{index:03d}" for index in range(474))
        cls.full_dates = weekdays(date(2024, 1, 2), 420)
        cls.model_dates = cls.full_dates[4:]
        rows = []
        for ticker_index, ticker in enumerate(cls.tickers):
            for session_index, session in enumerate(cls.full_dates):
                values = {column: None for column in MARKET_DAILY_FEATURE_COLUMNS}
                adjusted = 100.0 + ticker_index + session_index / 10.0
                values.update({
                    "snapshot_id": "snapshot-v1", "ticker": ticker,
                    "date": session, "sector": "Synthetic",
                    "open_price": adjusted, "high_price": adjusted,
                    "low_price": adjusted, "close_price": adjusted,
                    "adjusted_close": adjusted, "volume": 1000.0,
                    "dividends": 0.0, "stock_splits": 0.0,
                    "daily_return_pct": 999.0,
                })
                rows.append(tuple(values[column] for column in MARKET_DAILY_FEATURE_COLUMNS))
        cls.rows = tuple(rows)
        cls.binding, cls.s07 = cls.make_bindings(cls.rows)
        temporary = TrustedReadbackBinding(
            cls.binding.dataset_version, cls.binding.snapshot_id,
            cls.binding.content_sha256, "0" * 64)
        cls.readback = replace(
            temporary, readback_evidence_sha256=trusted_readback_artifact_sha256(temporary))
        columns_raw = __import__("json").dumps(
            list(MARKET_DAILY_FEATURE_COLUMNS), sort_keys=True,
            separators=(",", ":"), ensure_ascii=True).encode()
        cls.serializer = ImportedSerializerBinding(
            "canonical.oracle_research_dataset_serializers.MarketDatasetStreamingDigester",
            "2" * 64, "3" * 64, hashlib.sha256(columns_raw).hexdigest())

    @classmethod
    def make_bindings(cls, rows, *, imputation_count=0):
        digester = MarketDatasetStreamingDigester(MARKET_DAILY_FEATURE_COLUMNS)
        digester.update_rows(rows)
        digest = digester.finalize()
        temporary = FrozenMarketBinding(
            dataset_version="dataset-v1", snapshot_id=digest.snapshot_id,
            content_sha256=digest.content_sha256,
            ticker_universe_sha256=digest.ticker_universe_sha256,
            row_count=digest.row_count, ticker_count=digest.ticker_count,
            full_session_dates=cls.full_dates,
            full_session_calendar_sha256=canonical_session_dates_sha256(cls.full_dates),
            upstream_imputation_count=imputation_count,
            binding_artifact_sha256="0" * 64,
        )
        binding = replace(temporary, binding_artifact_sha256=binding_artifact_sha256(temporary))
        s07 = S07SignalBinding(
            s07_raw_sha256="1" * 64,
            frozen_content_sha256=digest.content_sha256,
            model_session_dates=cls.model_dates,
            model_session_dates_sha256=canonical_session_dates_sha256(cls.model_dates),
            tickers=cls.tickers,
            ticker_list_sha256=canonical_ticker_list_sha256(cls.tickers),
        )
        return binding, s07

    def materialize(self, rows=None, binding=None, s07=None, readback=None, serializer=None):
        return materialize_signal_panel(
            canonical_rows=self.rows if rows is None else rows,
            market_binding=self.binding if binding is None else binding,
            s07_binding=self.s07 if s07 is None else s07,
            trusted_readback=self.readback if readback is None else readback,
            serializer_binding=self.serializer if serializer is None else serializer,
        )

    @staticmethod
    def readback_for(binding):
        temporary = TrustedReadbackBinding(
            binding.dataset_version, binding.snapshot_id,
            binding.content_sha256, "0" * 64)
        return replace(
            temporary,
            readback_evidence_sha256=trusted_readback_artifact_sha256(temporary),
        )

    def test_exact_panel_is_deterministic_ticker_major_float64_le(self):
        first = self.materialize()
        second = self.materialize()
        self.assertEqual(first, second)
        self.assertEqual(first.shape, (474, 416))
        self.assertEqual(len(first.ticker_major_f64le), 474 * 416 * 8)
        self.assertTrue(first.canonical_panel_bytes.startswith(b"V7PANEL\0"))
        self.assertEqual(first.panel_sha256, hashlib.sha256(first.canonical_panel_bytes).hexdigest())
        self.assertNotEqual(first.panel_sha256, hashlib.sha256(first.ticker_major_f64le).hexdigest())
        observed = struct.unpack("<d", first.ticker_major_f64le[:8])[0]
        self.assertEqual(observed, 100.4 / 100.3 - 1.0)
        self.assertEqual(first.signal_contract, SIGNAL_CONTRACT)
        self.assertEqual(first.float_contract, FLOAT_CONTRACT)
        self.assertEqual(first.database_writes, 0)
        self.assertEqual(first.downstream_outputs, 0)
        self.assertEqual(first.claimed_serializer_release_sha256, "2" * 64)
        self.assertEqual(first.claimed_zero_imputation_evidence_sha256,
                         self.binding.binding_artifact_sha256)
        self.assertEqual(first.authenticity_status,
                         "CLAIMED_UNVERIFIED_EXTERNAL_APPROVAL_ENVELOPE_REQUIRED")
        self.assertFalse(first.execution_authorized)

    def test_any_raw_row_or_corporate_action_drift_fails_frozen_content(self):
        for column, value in (("sector", "Drift"), ("stock_splits", 2.0),
                              ("daily_return_pct", -123.0), ("adjusted_close", 50.0)):
            attacked = list(self.rows)
            row = list(attacked[0])
            row[MARKET_DAILY_FEATURE_COLUMNS.index(column)] = value
            attacked[0] = tuple(row)
            with self.assertRaisesRegex(SignalPanelError, "readback differs"):
                self.materialize(rows=tuple(attacked))

    def test_binding_hash_and_s07_hash_drift_fail(self):
        with self.assertRaisesRegex(SignalPanelError, "binding artifact"):
            self.materialize(binding=replace(self.binding, content_sha256="f" * 64))
        with self.assertRaisesRegex(SignalPanelError, "S07 frozen content"):
            self.materialize(s07=replace(self.s07, frozen_content_sha256="f" * 64))
        with self.assertRaisesRegex(SignalPanelError, "model calendar digest"):
            self.materialize(s07=replace(self.s07, model_session_dates_sha256="f" * 64))

    def test_duplicate_or_drifted_date_and_ticker_fail(self):
        for column, value in (("date", self.full_dates[1]), ("ticker", "bad")):
            attacked = list(self.rows)
            row = list(attacked[0])
            row[MARKET_DAILY_FEATURE_COLUMNS.index(column)] = value
            attacked[0] = tuple(row)
            with self.assertRaisesRegex(SignalPanelError, "streaming digest rejected"):
                self.materialize(rows=tuple(attacked))

    def test_missing_nonfinite_and_nonpositive_adjusted_close_never_impute(self):
        adjusted_index = MARKET_DAILY_FEATURE_COLUMNS.index("adjusted_close")
        for value in (None, float("nan"), 0.0, -1.0):
            attacked = list(self.rows)
            row = list(attacked[3])
            row[adjusted_index] = value
            attacked[3] = tuple(row)
            attacked_rows = tuple(attacked)
            if value is None or value <= 0:
                binding, s07 = self.make_bindings(attacked_rows)
                with self.assertRaisesRegex(SignalPanelError, "adjusted_close"):
                    self.materialize(rows=attacked_rows, binding=binding, s07=s07,
                                     readback=self.readback_for(binding))
            else:
                with self.assertRaisesRegex(SignalPanelError, "streaming digest rejected"):
                    self.materialize(rows=attacked_rows)

    def test_upstream_imputation_attestation_must_be_zero(self):
        binding, s07 = self.make_bindings(self.rows, imputation_count=1)
        with self.assertRaisesRegex(SignalPanelError, "imputed"):
            self.materialize(binding=binding, s07=s07)

    def test_dataset_version_must_match_trusted_readback(self):
        attacked = replace(self.readback, dataset_version="fabricated-version")
        attacked = replace(
            attacked,
            readback_evidence_sha256=trusted_readback_artifact_sha256(attacked),
        )
        with self.assertRaisesRegex(SignalPanelError, "dataset version"):
            self.materialize(readback=attacked)

    def test_bool_and_empty_identity_values_are_rejected_even_if_self_hashed(self):
        for value in (True, False, ""):
            market = replace(self.binding, dataset_version=value,
                             binding_artifact_sha256="0" * 64)
            market = replace(market,
                             binding_artifact_sha256=binding_artifact_sha256(market))
            readback = replace(self.readback, dataset_version=value,
                               readback_evidence_sha256="0" * 64)
            readback = replace(
                readback,
                readback_evidence_sha256=trusted_readback_artifact_sha256(readback),
            )
            with self.subTest(value=value), self.assertRaisesRegex(
                    SignalPanelError, "exact nonempty str"):
                self.materialize(binding=market, readback=readback)

    def test_coherent_self_hashed_claims_never_become_authority(self):
        market = replace(self.binding, dataset_version="coherent-claim",
                         binding_artifact_sha256="0" * 64)
        market = replace(market,
                         binding_artifact_sha256=binding_artifact_sha256(market))
        readback = replace(self.readback, dataset_version="coherent-claim",
                           readback_evidence_sha256="0" * 64)
        readback = replace(
            readback,
            readback_evidence_sha256=trusted_readback_artifact_sha256(readback),
        )
        panel = self.materialize(binding=market, readback=readback)
        self.assertEqual(panel.dataset_version, "coherent-claim")
        self.assertTrue(panel.authenticity_status.startswith("CLAIMED_UNVERIFIED"))
        self.assertFalse(panel.execution_authorized)
        self.assertNotIn("verified", panel.authenticity_status.lower().replace("unverified", ""))

    def test_all_injected_authenticity_boundaries_are_explicitly_claimed(self):
        panel = self.materialize()
        claimed = {name for name in panel.__dataclass_fields__ if name.startswith("claimed_")}
        self.assertEqual({
            "claimed_readback_evidence_sha256", "claimed_serializer_identity",
            "claimed_serializer_release_sha256", "claimed_serializer_source_sha256",
            "claimed_serializer_feature_columns_sha256",
            "claimed_zero_imputation_evidence_sha256", "claimed_s07_evidence_sha256",
            "claimed_full_calendar_evidence_sha256",
        }, claimed)
        self.assertFalse(any(name.startswith("verified_")
                             for name in panel.__dataclass_fields__))

    def test_trusted_readback_digest_cannot_be_self_attested_by_label(self):
        with self.assertRaisesRegex(SignalPanelError, "readback evidence"):
            self.materialize(readback=replace(
                self.readback, readback_evidence_sha256="f" * 64))

    def test_imported_serializer_identity_and_release_are_bound(self):
        with self.assertRaisesRegex(SignalPanelError, "feature-column"):
            self.materialize(serializer=replace(
                self.serializer, feature_columns_sha256="f" * 64))
        with self.assertRaisesRegex(SignalPanelError, "nonempty str"):
            self.materialize(serializer=replace(self.serializer, serializer_identity=""))
        panel = self.materialize(serializer=replace(
            self.serializer, serializer_release_sha256="e" * 64))
        self.assertEqual(panel.claimed_serializer_release_sha256, "e" * 64)

    def test_model_calendar_requires_exact_consecutive_416_and_prior_session(self):
        attacked_dates = (self.full_dates[0], *self.model_dates[1:])
        attacked = replace(
            self.s07, model_session_dates=attacked_dates,
            model_session_dates_sha256=canonical_session_dates_sha256(attacked_dates),
        )
        with self.assertRaisesRegex(SignalPanelError, "lacks an immediately preceding"):
            self.materialize(s07=attacked)
        gapped_dates = (*self.model_dates[:10], self.full_dates[12], *self.model_dates[11:])
        attacked = replace(
            self.s07, model_session_dates=gapped_dates,
            model_session_dates_sha256=canonical_session_dates_sha256(gapped_dates),
        )
        with self.assertRaisesRegex(SignalPanelError, "duplicated, unordered"):
            self.materialize(s07=attacked)

    def test_stored_daily_return_is_never_used(self):
        panel = self.materialize()
        observed = struct.unpack("<d", panel.ticker_major_f64le[:8])[0]
        self.assertNotEqual(observed, 999.0)

    def test_lifecycle_gap_outside_required_417_date_subset_is_allowed(self):
        # T000/full_dates[0] is outside preceding+416 required dates.
        attacked_rows = self.rows[1:]
        binding, s07 = self.make_bindings(attacked_rows)
        panel = self.materialize(rows=attacked_rows, binding=binding, s07=s07,
                                 readback=self.readback_for(binding))
        self.assertEqual(binding.row_count, len(self.rows) - 1)
        self.assertEqual(panel.shape, (474, 416))

    def test_missing_required_subset_row_fails_even_with_rebound_full_content(self):
        # T000/full_dates[3] is the immediately preceding required session.
        attacked_rows = (*self.rows[:3], *self.rows[4:])
        binding, s07 = self.make_bindings(attacked_rows)
        with self.assertRaisesRegex(SignalPanelError, "required 474-by-417"):
            self.materialize(rows=attacked_rows, binding=binding, s07=s07,
                             readback=self.readback_for(binding))


if __name__ == "__main__":
    unittest.main()
