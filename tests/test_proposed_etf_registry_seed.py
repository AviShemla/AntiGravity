import unittest

from scripts.seed_proposed_etf_instrument_registry import (
    BENCHMARKS,
    MODEL_CANDIDATES,
    QUARANTINED,
    VALUATION_ONLY,
    evidence_sha256,
    proposed_instruments,
)


class ProposedETFRegistrySeedTests(unittest.TestCase):
    def test_proposal_is_complete_disjoint_and_hashable(self):
        groups = [set(MODEL_CANDIDATES), set(VALUATION_ONLY), set(BENCHMARKS), set(QUARANTINED)]
        self.assertEqual(sum(len(group) for group in groups), 26)
        self.assertEqual(len(set.union(*groups)), 26)
        self.assertEqual(len(evidence_sha256()), 64)

    def test_short_history_etfs_are_quarantined(self):
        self.assertTrue({"MRVU", "NBIL", "RGTZ"}.issubset(set(QUARANTINED)))

    def test_seed_rows_are_deterministic(self):
        rows = proposed_instruments("2026-08-22T00:00:00+00:00")
        self.assertEqual(len(rows), 26)
        self.assertEqual([row[1] for row in rows], sorted(row[1] for row in rows))


if __name__ == "__main__":
    unittest.main()
