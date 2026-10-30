import unittest

from scripts.apply_quarantine_fresh_start import (
    BENCHMARKS,
    LEGACY_QUARANTINED,
    MODEL_CANDIDATES,
    OBSERVATION_ONLY,
    REGISTRY_ID,
    evidence_sha256,
    registry_rows,
)


class QuarantineFreshStartScriptTests(unittest.TestCase):
    def test_previously_quarantined_symbols_become_observation_only(self):
        self.assertTrue(set(LEGACY_QUARANTINED).issubset(set(OBSERVATION_ONLY)))
        usage = {row[1]: row[4] for row in registry_rows("timestamp")}
        for ticker in LEGACY_QUARANTINED:
            self.assertEqual(usage[ticker], "VALUATION_ONLY")

    def test_registry_partition_is_exact(self):
        rows = registry_rows("timestamp")
        self.assertEqual(len(rows), 26)
        self.assertEqual(len({row[1] for row in rows}), 26)
        self.assertTrue(all(row[0] == REGISTRY_ID for row in rows))
        self.assertEqual(
            {row[1] for row in rows},
            set(MODEL_CANDIDATES) | set(OBSERVATION_ONLY) | set(BENCHMARKS),
        )

    def test_evidence_hash_is_stable_shape(self):
        checksum = evidence_sha256()
        self.assertEqual(len(checksum), 64)
        int(checksum, 16)


if __name__ == "__main__":
    unittest.main()
