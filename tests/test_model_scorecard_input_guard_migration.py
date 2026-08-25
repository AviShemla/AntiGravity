import unittest
from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260825_model_scorecard_input_guards_additive.sql"
)


class ModelScorecardInputGuardMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.compact = " ".join(cls.sql.split()).upper()

    def test_is_additive_and_review_only(self):
        self.assertIn("REVIEW-ONLY", self.sql)
        self.assertIn("CREATE TRIGGER IF NOT EXISTS", self.compact)
        for forbidden in ("DROP TABLE", "DELETE FROM", "UPDATE MODEL_RUNS", "UPDATE MODEL_RUN_INPUTS"):
            self.assertNotIn(forbidden, self.compact)

    def test_insert_guard_rechecks_exact_stock_run_state(self):
        self.assertIn("RUN.ASSET_CLASS = 'STOCK'", self.compact)
        self.assertIn("RUN.STATUS = 'STARTED'", self.compact)
        self.assertIn("RUN.SOURCE_SESSION_DATE < RUN.PREDICTION_DATE", self.compact)
        self.assertIn("SELECT COUNT(*) FROM MODEL_RUN_INPUTS INPUT", self.compact)
        self.assertIn(") = 2", self.compact)

    def test_market_binding_requires_validated_exact_lineage(self):
        self.assertIn("INPUT.INPUT_ROLE = 'MARKET_FEATURES'", self.compact)
        self.assertIn("SNAPSHOT.DATASET_TYPE = 'MARKET_FEATURES'", self.compact)
        self.assertIn("SNAPSHOT.STATUS = 'VALIDATED'", self.compact)
        self.assertIn(
            "INPUT.SNAPSHOT_CHECKSUM_SHA256 = SNAPSHOT.SOURCE_CHECKSUM_SHA256",
            self.compact,
        )
        self.assertIn(
            "SNAPSHOT.SOURCE_SESSION_DATE = RUN.SOURCE_SESSION_DATE",
            self.compact,
        )
        self.assertIn(
            "SNAPSHOT.AVAILABLE_AT_UTC <= RUN.AS_OF_TIMESTAMP_UTC",
            self.compact,
        )

    def test_universe_binding_requires_latest_approval_before_cutoff(self):
        self.assertIn("INPUT.INPUT_ROLE = 'STOCK_UNIVERSE'", self.compact)
        self.assertIn("SNAPSHOT.DATASET_TYPE = 'STOCK_UNIVERSE'", self.compact)
        self.assertIn("APPROVAL.DECISION = 'APPROVED'", self.compact)
        self.assertIn(
            "APPROVAL.SNAPSHOT_CHECKSUM_SHA256 = SNAPSHOT.SOURCE_CHECKSUM_SHA256",
            self.compact,
        )
        self.assertIn(
            "APPROVAL.DECIDED_AT_UTC <= RUN.AS_OF_TIMESTAMP_UTC",
            self.compact,
        )
        self.assertIn("ORDER BY LATEST.DECIDED_AT_UTC DESC, LATEST.EVENT_ID DESC", self.compact)

    def test_scorecards_are_immutable(self):
        self.assertIn("TRG_MODEL_SCORECARDS_LINEAGE_UPDATE", self.compact)
        self.assertIn("MODEL_SCORECARDS_ARE_IMMUTABLE", self.compact)
        self.assertIn("RAISE(ABORT", self.compact)


if __name__ == "__main__":
    unittest.main()
