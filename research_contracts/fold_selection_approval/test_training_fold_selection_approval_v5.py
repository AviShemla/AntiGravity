import dataclasses
import json
import unittest
from datetime import date, timedelta

from .training_fold_selection_approval_v5 import (
    EXPECTED_CANDIDATES_PER_FOLD, FOLD_GEOMETRY, ProposalError, ProposalInputs,
    build_proposal, candidate_ordinal, canonical_json_bytes, preflight,
    reconstruct_candidate, sha256,
)


def make_inputs(**changes):
    tickers = tuple(f"T{i:03d}" for i in range(474))
    ticker_raw = canonical_json_bytes(list(tickers))
    base = dict(
        tickers=tickers,
        frozen_session_dates=tuple((date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(416)),
        derivation_cutoff_utc="2026-08-25T23:55:00Z",
        frozen_dataset_version="oracle-research-v1", frozen_content_sha256="1" * 64,
        frozen_readback_sha256="2" * 64, frozen_readback_at_utc="2026-08-25T23:58:00Z",
        snapshot_id="snapshot-v1", snapshot_sha256="3" * 64,
        preregistration_sha256="4" * 64, selector_source_bytes=b"selector\n",
        selector_git_commit="5" * 40, selector_release_bytes=b"release\n",
        dependency_lock_bytes=b"lock\n", verifier_source_bytes=b"verifier\n")
    lineage = {
        "contract": "exact-frozen-ticker-universe-lineage-v1",
        "frozen_dataset_version": base["frozen_dataset_version"],
        "snapshot_id": base["snapshot_id"], "snapshot_sha256": base["snapshot_sha256"],
        "ticker_count": 474, "ticker_universe_bytes_sha256": sha256(ticker_raw)}
    base["universe_lineage_bytes"] = canonical_json_bytes(lineage)
    base.update(changes)
    return ProposalInputs(**base)


class ApprovalProposalV5Tests(unittest.TestCase):
    def test_valid_proposal_stays_fail_closed(self):
        result = preflight(build_proposal(make_inputs()), approval=b"fabricated")
        self.assertEqual("APPROVAL_REQUIRED", result.status)
        self.assertEqual((), result.selections)

    def test_contradictory_ticker_lineage_rejected(self):
        p = make_inputs()
        lineage = json.loads(p.universe_lineage_bytes)
        lineage["ticker_universe_bytes_sha256"] = "f" * 64
        with self.assertRaisesRegex(ProposalError, "contradicts"):
            build_proposal(dataclasses.replace(p, universe_lineage_bytes=canonical_json_bytes(lineage)))

    def test_contradictory_snapshot_lineage_rejected(self):
        p = make_inputs()
        lineage = json.loads(p.universe_lineage_bytes)
        lineage["snapshot_sha256"] = "e" * 64
        with self.assertRaisesRegex(ProposalError, "contradicts"):
            build_proposal(dataclasses.replace(p, universe_lineage_bytes=canonical_json_bytes(lineage)))

    def test_invalid_z_timestamps_rejected(self):
        invalid = ["2026-02-30T00:00:00Z", "2026-08-25 23:55:00Z",
                   "2026-08-25T23:55Z", "2026-08-25T23:55:00+00:00",
                   "2026-08-25T23:55:00.1234567Z"]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ProposalError):
                build_proposal(dataclasses.replace(make_inputs(), derivation_cutoff_utc=value))

    def test_readback_must_not_precede_cutoff(self):
        with self.assertRaisesRegex(ProposalError, "cannot precede"):
            build_proposal(dataclasses.replace(make_inputs(),
                frozen_readback_at_utc="2026-08-25T23:54:59Z"))

    def test_every_ordinal_round_trips_complete_family(self):
        for ordinal in range(EXPECTED_CANDIDATES_PER_FOLD):
            t, s, lag = reconstruct_candidate(ordinal)
            self.assertNotEqual(t, s)
            self.assertEqual(ordinal, candidate_ordinal(t, s, lag))

    def test_enumeration_is_target_then_source_then_lag(self):
        self.assertEqual((0, 1, 1), reconstruct_candidate(0))
        self.assertEqual((0, 1, 7), reconstruct_candidate(6))
        self.assertEqual((0, 2, 1), reconstruct_candidate(7))
        self.assertEqual((1, 0, 1), reconstruct_candidate(3311))

    def test_exact_fold_geometry_has_zero_internal_overlap(self):
        self.assertEqual(4, len(FOLD_GEOMETRY))
        for g in FOLD_GEOMETRY:
            train = set(range(g["train_start_index"], g["train_end_index"] + 1))
            purge = set(range(g["purge_start_index"], g["purge_end_index"] + 1))
            test = set(range(g["test_start_index"], g["test_end_index"] + 1))
            self.assertFalse(train & purge or train & test or purge & test)
            self.assertEqual((289, 7, 30), (len(train), len(purge), len(test)))

    def test_fold_geometry_is_bound_to_exact_calendar_dates(self):
        p = build_proposal(make_inputs())
        geometry = json.loads(p.artifacts["fold_geometry.json"])
        calendar = json.loads(p.artifacts["frozen_session_calendar.json"])
        self.assertEqual(sha256(p.artifacts["frozen_session_calendar.json"]),
                         geometry["calendar_bytes_sha256"])
        for fold in geometry["folds"]:
            self.assertEqual(calendar[fold["train_start_index"]], fold["train_start_date"])
            self.assertEqual(calendar[fold["test_end_index"]], fold["test_end_date"])

    def test_exact_snapshot_sha_is_in_core_and_approval_wording(self):
        p = build_proposal(make_inputs())
        core, approval = json.loads(p.proposal_core_bytes), json.loads(p.approval_record_bytes)
        self.assertEqual("3" * 64, core["snapshot_sha256"])
        self.assertIn("3" * 64, approval["required_exact_wording"])

    def test_proposal_is_reproducible(self):
        a, b = build_proposal(make_inputs()), build_proposal(make_inputs())
        self.assertEqual(a.proposal_core_bytes, b.proposal_core_bytes)
        self.assertEqual(a.approval_record_bytes, b.approval_record_bytes)
        self.assertEqual(dict(a.artifact_sha256), dict(b.artifact_sha256))


if __name__ == "__main__":
    unittest.main()
