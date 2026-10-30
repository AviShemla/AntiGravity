import unittest
from dataclasses import replace

from instrument_registry import (
    InstrumentSpec,
    InstrumentUsage,
    RegistryStatus,
    RegistryVersion,
    validate_registry_for_model_use,
)
from model_lineage import AssetClass, LineageError


def version(status=RegistryStatus.APPROVED):
    return RegistryVersion(
        registry_id="registry-1",
        status=status,
        evidence_as_of_date="2026-08-21",
        source_evidence={"source": "Turso audit"},
        approved_by="AviShemla" if status is RegistryStatus.APPROVED else None,
        approved_at_utc="2026-08-22T05:00:00+00:00" if status is RegistryStatus.APPROVED else None,
    )


def stock():
    return InstrumentSpec(
        "registry-1", "AAPL", AssetClass.STOCK, "Technology",
        InstrumentUsage.MODEL_CANDIDATE, 252, "validated stock universe",
    )


def etf():
    return InstrumentSpec(
        "registry-1", "XLK", AssetClass.ETF, "ETF",
        InstrumentUsage.MODEL_CANDIDATE, 252, "approved sector ETF",
    )


class InstrumentRegistryTests(unittest.TestCase):
    def test_approved_complete_registry_passes(self):
        self.assertEqual(len(validate_registry_for_model_use(version(), [stock(), etf()])), 2)

    def test_draft_registry_cannot_control_model(self):
        with self.assertRaisesRegex(LineageError, "approved"):
            validate_registry_for_model_use(version(RegistryStatus.DRAFT), [stock(), etf()])

    def test_duplicate_ticker_is_rejected(self):
        with self.assertRaisesRegex(LineageError, "duplicate"):
            validate_registry_for_model_use(version(), [stock(), etf(), etf()])

    def test_registry_without_etf_model_candidate_is_rejected(self):
        with self.assertRaisesRegex(LineageError, "ETF model candidate"):
            validate_registry_for_model_use(
                version(),
                [stock(), replace(etf(), usage=InstrumentUsage.VALUATION_ONLY)],
            )

    def test_invalid_ticker_is_rejected(self):
        with self.assertRaisesRegex(LineageError, "ticker"):
            replace(etf(), ticker="DROP TABLE").validate_for(version())


if __name__ == "__main__":
    unittest.main()
