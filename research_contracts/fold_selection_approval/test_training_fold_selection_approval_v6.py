from __future__ import annotations

import dataclasses
from datetime import date, timedelta
import json
import unittest

from .training_fold_selection_approval_v5 import canonical_json_bytes, sha256
from .training_fold_selection_approval_v6 import (
    ELIGIBLE_TICKER_COUNT, EXPECTED_CANDIDATES_PER_FOLD,
    EXPECTED_OOS_OBSERVATIONS, EXPECTED_TARGET_FOLD_GROUPS,
    EXPECTED_TOTAL_HYPOTHESES, PRESENCE_MASK_CONTRACT, ProposalError,
    ProposalInputs, build_proposal, candidate_ordinal, preflight,
    reconstruct_candidate,
)


def make_inputs(**changes) -> ProposalInputs:
    ordinary = [f"T{i:03d}" for i in range(472)]
    tickers = tuple(sorted(ordinary + ["FISV", "SNDK"]))
    dates = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(417)]
    rows = []
    for ticker in tickers:
        count = {"FISV": 416, "SNDK": 358}.get(ticker, 417)
        rows.append("1" * count + "0" * (417 - count))
    mask = canonical_json_bytes({
        "contract": PRESENCE_MASK_CONTRACT,
        "session_dates": dates,
        "ticker_order": list(tickers),
        "presence_rows": rows,
    })
    eligible = tuple(t for t in tickers if t not in {"FISV", "SNDK"})
    values = dict(
        upstream_tickers=tickers,
        presence_mask_bytes=mask,
        upstream_universe_sha256=sha256(canonical_json_bytes(list(tickers))),
        presence_mask_sha256=sha256(mask),
        eligible_universe_sha256=sha256(canonical_json_bytes(list(eligible))),
        prior_preregistration_sha256="a" * 64,
    )
    values.update(changes)
    return ProposalInputs(**values)


class ApprovalProposalV6Tests(unittest.TestCase):
    def test_exact_counts_lineage_and_fail_closed_boundary(self):
        proposal = build_proposal(make_inputs())
        core = json.loads(proposal.proposal_core_bytes)
        self.assertEqual((472, 4, 1_556_184, 6_224_736, 1_888, 56_640),
                         (core["eligible_ticker_count"], core["fold_count"],
                          core["candidates_per_fold"], core["total_hypotheses"],
                          core["target_fold_groups"], core["oos_observations"]))
        self.assertFalse(core["execution_authorized"])
        result = preflight(proposal, approval=b"fabricated", execute=True)
        self.assertEqual(("APPROVAL_REQUIRED", (), None),
                         (result.status, result.selections, result.pinned_approval_record_sha256))

    def test_eligible_universe_is_sorted_472_and_excludes_both_roles(self):
        proposal = build_proposal(make_inputs())
        eligible = json.loads(proposal.artifacts["eligible_universe.json"])
        exclusions = json.loads(proposal.artifacts["exclusions.json"])
        self.assertEqual(ELIGIBLE_TICKER_COUNT, len(eligible))
        self.assertEqual(sorted(eligible), eligible)
        self.assertNotIn("FISV", eligible); self.assertNotIn("SNDK", eligible)
        self.assertEqual({"FISV": 416, "SNDK": 358}, exclusions["excluded_from_target"])
        self.assertEqual(exclusions["excluded_from_target"], exclusions["excluded_from_source"])
        self.assertIn("ZERO_IMPUTATION", exclusions["rule"])

    def test_every_ordinal_is_an_exact_bijection(self):
        self.assertEqual(EXPECTED_CANDIDATES_PER_FOLD, 472 * 471 * 7)
        seen = set()
        for ordinal in range(EXPECTED_CANDIDATES_PER_FOLD):
            candidate = reconstruct_candidate(ordinal)
            self.assertNotEqual(candidate[0], candidate[1])
            self.assertEqual(ordinal, candidate_ordinal(*candidate))
            seen.add(candidate)
        self.assertEqual(EXPECTED_CANDIDATES_PER_FOLD, len(seen))
        self.assertEqual((0, 1, 1), reconstruct_candidate(0))
        self.assertEqual((1, 0, 1), reconstruct_candidate(3297))

    def test_constants_reconcile_without_rounding(self):
        self.assertEqual(EXPECTED_TOTAL_HYPOTHESES, 4 * EXPECTED_CANDIDATES_PER_FOLD)
        self.assertEqual(EXPECTED_TARGET_FOLD_GROUPS, 4 * 472)
        self.assertEqual(EXPECTED_OOS_OBSERVATIONS, 4 * 472 * 30)

    def test_all_upstream_hashes_are_bound_in_lineage(self):
        values = make_inputs(); proposal = build_proposal(values)
        lineage = json.loads(proposal.artifacts["lineage.json"])
        self.assertEqual(values.upstream_universe_sha256, lineage["upstream_universe_sha256"])
        self.assertEqual(values.presence_mask_sha256, lineage["presence_mask_sha256"])
        self.assertEqual(values.eligible_universe_sha256, lineage["eligible_universe_sha256"])
        self.assertEqual(values.prior_preregistration_sha256, lineage["prior_preregistration_sha256"])
        self.assertTrue(lineage["zero_imputation"])

    def test_tampered_hashes_and_mask_bytes_are_rejected(self):
        base = make_inputs()
        for field in ("upstream_universe_sha256", "presence_mask_sha256",
                      "eligible_universe_sha256"):
            with self.subTest(field=field), self.assertRaises(ProposalError):
                build_proposal(dataclasses.replace(base, **{field: "f" * 64}))
        with self.assertRaisesRegex(ProposalError, "prior_preregistration_sha256"):
            build_proposal(dataclasses.replace(base, prior_preregistration_sha256="not-a-sha"))
        with self.assertRaisesRegex(ProposalError, "mask hash"):
            build_proposal(dataclasses.replace(base, presence_mask_bytes=base.presence_mask_bytes + b" "))

    def test_noncanonical_or_malformed_presence_masks_are_rejected(self):
        base = make_inputs(); obj = json.loads(base.presence_mask_bytes)
        variants = []
        variants.append(json.dumps(obj).encode())
        bad = dict(obj); bad["session_dates"] = bad["session_dates"][:-1]; variants.append(canonical_json_bytes(bad))
        bad = dict(obj); bad["ticker_order"] = list(reversed(bad["ticker_order"])); variants.append(canonical_json_bytes(bad))
        bad = dict(obj); bad["presence_rows"] = list(bad["presence_rows"]); bad["presence_rows"][0] = "2" * 417; variants.append(canonical_json_bytes(bad))
        bad = dict(obj); bad["session_dates"] = list(bad["session_dates"]); bad["session_dates"][0] = "not-a-date"; variants.append(canonical_json_bytes(bad))
        for raw in variants:
            with self.subTest(size=len(raw)), self.assertRaises(ProposalError):
                build_proposal(dataclasses.replace(base, presence_mask_bytes=raw,
                                                    presence_mask_sha256=sha256(raw)))

    def test_wrong_exclusion_counts_or_set_fail_closed(self):
        base = make_inputs(); obj = json.loads(base.presence_mask_bytes)
        fisv = obj["ticker_order"].index("FISV")
        sndk = obj["ticker_order"].index("SNDK")
        for index, row in ((fisv, "1" * 415 + "00"), (sndk, "1" * 359 + "0" * 58)):
            bad = json.loads(base.presence_mask_bytes)
            bad["presence_rows"][index] = row
            raw = canonical_json_bytes(bad)
            with self.assertRaisesRegex(ProposalError, "presence count"):
                build_proposal(dataclasses.replace(base, presence_mask_bytes=raw,
                                                    presence_mask_sha256=sha256(raw)))
        bad = json.loads(base.presence_mask_bytes)
        bad["presence_rows"][fisv] = "1" * 417
        raw = canonical_json_bytes(bad)
        with self.assertRaisesRegex(ProposalError, "eligible universe|exclusion set"):
            build_proposal(dataclasses.replace(base, presence_mask_bytes=raw,
                                                presence_mask_sha256=sha256(raw)))

    def test_ordinal_adversarial_boundaries_are_rejected(self):
        for values in ((-1, 0, 1), (472, 0, 1), (0, 472, 1), (0, 0, 1),
                       (0, 1, 0), (0, 1, 8), (True, 1, 1), (0, False, 1),
                       (0, 1, True)):
            with self.subTest(values=values), self.assertRaises(ProposalError):
                candidate_ordinal(*values)
        for ordinal in (-1, EXPECTED_CANDIDATES_PER_FOLD, True, 1.5):
            with self.subTest(ordinal=ordinal), self.assertRaises(ProposalError):
                reconstruct_candidate(ordinal)

    def test_proposal_reproducible_and_has_no_execution_artifact(self):
        a, b = build_proposal(make_inputs()), build_proposal(make_inputs())
        self.assertEqual(a, b)
        names = set(vars(__import__(a.__class__.__module__, fromlist=["*"])))
        self.assertTrue(names.isdisjoint({"execute", "run", "sample", "connect", "open", "sqlite3"}))


if __name__ == "__main__":
    unittest.main()
