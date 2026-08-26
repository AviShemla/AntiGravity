import json
import unittest

from model_lineage import LineageError
from screening_terminal_outcome import (
    CandidateScreeningEvidence,
    DownstreamOutputCounts,
    NO_QUALIFYING_OUTPUT,
    ScreeningArmEvidence,
    build_no_qualifying_output_evidence,
)


ZERO = DownstreamOutputCounts(model_runs=0, model_scorecards=0, etf_priors=0)


def evaluated(ticker="AAA", *, eligible=False):
    return CandidateScreeningEvidence(
        ticker=ticker,
        eligible=eligible,
        rejection_reasons=("ACCURACY_CI_DOES_NOT_BEAT_MAJORITY",),
        oos_sessions=120,
        oos_accuracy=0.55,
        accuracy_ci_low=0.45,
        accuracy_ci_high=0.64,
        brier_score=0.24,
        log_loss=0.68,
        calibration_error=0.08,
        majority_accuracy=0.52,
        own_lag_accuracy=0.53,
        own_lag_brier=0.25,
        selected_depth=2,
        feature_spec_json=json.dumps({"depth": 2, "lag_tickers": ["BBB", "CCC"]}),
    )


def rejected(ticker="BBB"):
    return CandidateScreeningEvidence(
        ticker=ticker,
        eligible=False,
        rejection_reasons=("NO_ADMISSIBLE_INNER_SPEC",),
        oos_sessions=0,
    )


def arm(run_id="run-60", *, candidates=None, code="abc123", status="VALIDATED"):
    rows = tuple(candidates or (evaluated(), rejected()))
    return ScreeningArmEvidence(
        screening_run_id=run_id,
        market_snapshot_id="snapshot-2026-08-25",
        snapshot_checksum_sha256="a" * 64,
        snapshot_status="VALIDATED",
        source_session_date="2026-08-25",
        cutoff_utc="2026-08-26T07:00:00+00:00",
        code_version=code,
        config_json=json.dumps(
            {"eligibility_hypotheses": len(rows), "signal_lookback_sessions": 60},
            separators=(",", ":"),
        ),
        run_status=status,
        validation_notes="full coverage and zero unauthorized outputs",
        expected_ticker_count=len(rows),
        candidates=rows,
    )


class NoQualifyingOutputTests(unittest.TestCase):
    def test_builds_terminal_evidence_without_fabricating_outputs(self):
        result = build_no_qualifying_output_evidence([arm()], downstream=ZERO)
        self.assertEqual(result.state, NO_QUALIFYING_OUTPUT)
        self.assertTrue(result.terminal)
        self.assertFalse(result.production_promotion_allowed)
        self.assertEqual(result.downstream, ZERO)
        summary = result.arms[0].metrics
        self.assertEqual(summary.evaluated_candidates, 1)
        self.assertEqual(summary.data_rejected_candidates, 1)
        self.assertEqual(summary.mean_oos_accuracy, 0.55)
        self.assertEqual(summary.mean_majority_accuracy, 0.52)
        self.assertEqual(result.arms[0].arm.candidates[0].brier_score, 0.24)
        self.assertEqual(
            [(item.reason, item.count) for item in result.arms[0].rejection_reason_counts],
            [("ACCURACY_CI_DOES_NOT_BEAT_MAJORITY", 1), ("NO_ADMISSIBLE_INNER_SPEC", 1)],
        )

    def test_outcome_identity_is_deterministic_across_arm_order(self):
        second = arm("run-126")
        one = build_no_qualifying_output_evidence([arm(), second], downstream=ZERO)
        two = build_no_qualifying_output_evidence([second, arm()], downstream=ZERO)
        self.assertEqual(one.outcome_id, two.outcome_id)

    def test_empty_or_nonvalidated_evidence_fails_closed(self):
        with self.assertRaisesRegex(LineageError, "at least one"):
            build_no_qualifying_output_evidence([], downstream=ZERO)
        with self.assertRaisesRegex(LineageError, "validated screening"):
            build_no_qualifying_output_evidence([arm(status="RUNNING")], downstream=ZERO)

    def test_eligible_candidate_cannot_enter_terminal_path(self):
        with self.assertRaisesRegex(LineageError, "eligible candidate"):
            build_no_qualifying_output_evidence(
                [arm(candidates=(evaluated(eligible=True), rejected()))], downstream=ZERO
            )

    def test_incomplete_or_duplicate_coverage_fails_closed(self):
        incomplete = arm()
        incomplete = ScreeningArmEvidence(
            **{**incomplete.__dict__, "expected_ticker_count": 3}
        )
        with self.assertRaisesRegex(LineageError, "coverage is incomplete"):
            build_no_qualifying_output_evidence([incomplete], downstream=ZERO)
        with self.assertRaisesRegex(LineageError, "duplicate tickers"):
            build_no_qualifying_output_evidence(
                [arm(candidates=(evaluated(), rejected("AAA")))], downstream=ZERO
            )

    def test_metrics_are_required_for_evaluated_rows_and_forbidden_for_rejections(self):
        missing = evaluated()
        missing = CandidateScreeningEvidence(**{**missing.__dict__, "brier_score": None})
        with self.assertRaisesRegex(LineageError, "preserve all"):
            build_no_qualifying_output_evidence(
                [arm(candidates=(missing, rejected()))], downstream=ZERO
            )
        fabricated = CandidateScreeningEvidence(
            **{**rejected().__dict__, "oos_accuracy": 0.5}
        )
        with self.assertRaisesRegex(LineageError, "fabricated metrics"):
            build_no_qualifying_output_evidence(
                [arm(candidates=(evaluated(), fabricated))], downstream=ZERO
            )

    def test_lineage_mismatch_and_downstream_outputs_fail_closed(self):
        with self.assertRaisesRegex(LineageError, "exact snapshot, cutoff, and code lineage"):
            build_no_qualifying_output_evidence(
                [arm(), arm("run-other", code="different")], downstream=ZERO
            )
        with self.assertRaisesRegex(LineageError, "zero downstream outputs"):
            build_no_qualifying_output_evidence(
                [arm()],
                downstream=DownstreamOutputCounts(
                    model_runs=1, model_scorecards=0, etf_priors=0
                ),
            )

    def test_cutoff_is_bound_to_shared_lineage_and_outcome_identity(self):
        source = arm()
        changed_cutoff = ScreeningArmEvidence(
            **{**arm("run-126").__dict__, "cutoff_utc": "2026-08-26T08:00:00+00:00"}
        )
        with self.assertRaisesRegex(LineageError, "exact snapshot, cutoff, and code lineage"):
            build_no_qualifying_output_evidence([source, changed_cutoff], downstream=ZERO)
        changed_single = ScreeningArmEvidence(
            **{**source.__dict__, "cutoff_utc": "2026-08-26T08:00:00+00:00"}
        )
        original = build_no_qualifying_output_evidence([source], downstream=ZERO)
        changed = build_no_qualifying_output_evidence([changed_single], downstream=ZERO)
        self.assertNotEqual(original.outcome_id, changed.outcome_id)

    def test_lineage_dates_and_governed_depth_fail_closed(self):
        source = arm()
        naive = ScreeningArmEvidence(
            **{**source.__dict__, "cutoff_utc": "2026-08-26T07:00:00"}
        )
        with self.assertRaisesRegex(LineageError, "timezone-aware"):
            build_no_qualifying_output_evidence([naive], downstream=ZERO)
        bad_date = ScreeningArmEvidence(
            **{**source.__dict__, "source_session_date": "2026-8-25"}
        )
        with self.assertRaisesRegex(LineageError, "ISO calendar date"):
            build_no_qualifying_output_evidence([bad_date], downstream=ZERO)
        too_deep = CandidateScreeningEvidence(
            **{**evaluated().__dict__, "selected_depth": 6,
               "feature_spec_json": json.dumps({"depth": 6})}
        )
        with self.assertRaisesRegex(LineageError, "depth 1..5"):
            build_no_qualifying_output_evidence(
                [arm(candidates=(too_deep, rejected()))], downstream=ZERO
            )

    def test_config_is_preserved_and_familywise_contract_is_required(self):
        source = arm()
        result = build_no_qualifying_output_evidence([source], downstream=ZERO)
        self.assertEqual(result.arms[0].arm.config_json, source.config_json)
        bad = ScreeningArmEvidence(
            **{
                **source.__dict__,
                "config_json": '{"eligibility_hypotheses":999}',
            }
        )
        with self.assertRaisesRegex(LineageError, "Familywise"):
            build_no_qualifying_output_evidence([bad], downstream=ZERO)


if __name__ == "__main__":
    unittest.main()
