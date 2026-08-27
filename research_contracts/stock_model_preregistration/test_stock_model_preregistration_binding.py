import copy
from datetime import date, datetime, timedelta, timezone
from dataclasses import fields
from unittest import mock
import unittest

try:
    from . import stock_model_preregistration_binding as binding
    from .stock_model_preregistration import (
        BaselineReadbackProof, PreregistrationError,
        audit_preregistration_manifest, canonical_sha,
    )
except ImportError:
    import stock_model_preregistration_binding as binding
    from stock_model_preregistration import (
        BaselineReadbackProof, PreregistrationError,
        audit_preregistration_manifest, canonical_sha,
    )


class V4BindingTests(unittest.TestCase):
    def setUp(self):
        end = date(2026, 8, 25)
        self.sessions = [(end - timedelta(days=1_245 - i)).isoformat() for i in range(1_246)]
        self.session_sha = canonical_sha(self.sessions)
        self.tickers = [f"T{i:03d}" for i in range(474)]
        self.lineage = {
            "snapshot_id": binding.SNAPSHOT_ID,
            "snapshot_sha256": binding.SNAPSHOT_SHA256,
            "source_session_date": binding.SOURCE_SESSION_DATE,
            "screening_code_version": binding.SCREENING_CODE_VERSION,
            "screening_runs": [dict(item) for item in binding.EXPECTED_ARMS],
            "common_config": dict(binding.EXPECTED_COMMON_CONFIG),
            "ticker_universe": list(self.tickers),
            "ticker_universe_sha256": canonical_sha(self.tickers),
            "sessions": list(self.sessions),
            "sessions_sha256": self.session_sha,
        }
        acc = {
            "observations": 56_880, "correct": 0, "brier_sum": 0.0,
            "log_loss_sum": 0.0,
            "calibration_bins": [
                {"count": 56_880 if i == 0 else 0, "truth_sum": 0,
                 "probability_sum": 0.0} for i in range(10)
            ],
        }
        pair = {"metrics": {"accuracy": 0.0, "brier": 0.0, "log_loss": 0.0,
                            "calibration_error": 0.0}, "accumulator": acc}
        deterministic = {
            "contract_id": binding.PRODUCER_CONTRACT_ID,
            "lineage_sha256": canonical_sha(self.lineage),
            "coverage": dict(binding.EXPECTED_COVERAGE),
            "aggregate": {name: copy.deepcopy(pair) for name in binding.MODEL_NAMES},
            "ticker_checkpoints": [
                {"ticker": ticker, "checkpoint_sha256": f"{i + 1:064x}"}
                for i, ticker in enumerate(self.tickers)
            ],
            "side_effects": dict(binding.ZERO_SIDE_EFFECTS),
        }
        self.completion = datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc)
        self.executor_commit = "1" * 40
        self.final = {
            **deterministic,
            "deterministic_evidence_sha256": canonical_sha(deterministic),
            "runtime": {"executor_git_commit": self.executor_commit,
                        "observed_at_utc": self.completion.isoformat()},
        }
        self.final_raw = "9" * 64
        self.immutable_raw = "8" * 64
        self.fresh_raw = "7" * 64
        self.immutable = self.audit(self.completion + timedelta(minutes=10), "2" * 64)
        self.fresh = self.audit(self.completion + timedelta(minutes=20), "2" * 64)
        self.observed = self.completion + timedelta(minutes=25)

    def audit(self, verified_at, executor_manifest_sha):
        evidence = {
            "audit_contract_id": binding.AUDIT_CONTRACT_ID,
            "audited_contract_id": binding.PRODUCER_CONTRACT_ID,
            "stage": "VERIFIED", "verified_at_utc": verified_at.isoformat(),
            "executor_git_commit": self.executor_commit,
            "coverage": dict(binding.EXPECTED_COVERAGE),
            "checks": {name: True for name in binding.AUDIT_CHECKS},
            "source_artifacts": {
                "executor_manifest_file_sha256": executor_manifest_sha,
                "final_manifest_file_sha256": self.final_raw,
                "final_deterministic_evidence_sha256": self.final["deterministic_evidence_sha256"],
                "checkpoint_file_set_sha256": "3" * 64,
                "live_session_count": 1_246, "live_session_sha256": self.session_sha,
                "live_downstream_schema_presence": {
                    name: "schema_absent" for name in binding.DOWNSTREAM_TABLES},
                "live_downstream_counts": dict(binding.ZERO_DOWNSTREAM),
                "live_select_statements": 3,
            },
            "side_effects": dict(binding.ZERO_SIDE_EFFECTS),
        }
        evidence["audit_evidence_sha256"] = canonical_sha(evidence)
        return evidence

    @staticmethod
    def resign_audit(audit):
        audit["audit_evidence_sha256"] = canonical_sha({
            key: value for key, value in audit.items() if key != "audit_evidence_sha256"})

    @staticmethod
    def resign_final(final):
        deterministic = {key: value for key, value in final.items()
                         if key not in {"deterministic_evidence_sha256", "runtime"}}
        final["deterministic_evidence_sha256"] = canonical_sha(deterministic)

    def bind(self, **changes):
        values = dict(
            final_manifest=self.final, immutable_audit=self.immutable,
            fresh_readback_audit=self.fresh, lineage_mapping=self.lineage,
            final_manifest_file_sha256=self.final_raw,
            immutable_audit_file_sha256=self.immutable_raw,
            fresh_readback_file_sha256=self.fresh_raw,
            current_model_git_commit="4" * 40, observed_at_utc=self.observed,
            run_id="stock-model-v4-bound-20260827",
        )
        values.update(changes)
        with mock.patch.multiple(
            binding,
            SESSION_SHA256=self.session_sha,
            PINNED_FINAL_MANIFEST_RAW_SHA256=self.final_raw,
            PINNED_IMMUTABLE_AUDIT_RAW_SHA256=self.immutable_raw,
            PINNED_IMMUTABLE_AUDIT_EMBEDDED_SHA256=self.immutable["audit_evidence_sha256"],
            PINNED_EXECUTOR_COMMIT=self.executor_commit,
            PINNED_EXECUTOR_MANIFEST_RAW_SHA256="2" * 64,
            PINNED_CHECKPOINT_SET_SHA256="3" * 64,
            PINNED_DETERMINISTIC_EVIDENCE_SHA256=self.final["deterministic_evidence_sha256"],
            PINNED_BASELINE_LINEAGE_SHA256=canonical_sha(self.lineage),
            PINNED_UNIVERSE_SHA256=self.lineage["ticker_universe_sha256"],
            PINNED_MODEL_SLICE_SHA256=canonical_sha(self.sessions[-416:]),
        ):
            return binding.bind_verified_v4_baseline(**values)

    def test_happy_path_is_fixture_only_pass_and_zero_execution(self):
        manifest = self.bind()
        self.assertEqual(manifest["preflight"]["status"], "PASS")
        self.assertTrue(manifest["preflight"]["fixture_only"])
        self.assertFalse(manifest["preflight"]["model_fit_authorized"])
        self.assertFalse(manifest["execution"]["model_fit_started"])
        self.assertEqual(manifest["sampler_config"], {
            "engine": "pymc-nuts", "chains": 4, "draws": 1000, "tune": 1000,
            "target_accept": 0.9, "random_seed": 20260827})
        expected_universe = (f"codex-oracle-stock-universe-v1:{binding.SNAPSHOT_ID}:"
                             f"{self.lineage['ticker_universe_sha256']}")
        self.assertEqual(manifest["lineage"]["universe_id"], expected_universe)
        self.assertEqual(tuple(manifest["model_session_dates"]), tuple(self.sessions[-416:]))

    def test_mapping_schema_and_duplicate_ticker_fail_closed(self):
        malformed = dict(self.lineage, extra=True)
        with self.assertRaises(PreregistrationError):
            self.bind(lineage_mapping=malformed)
        duplicate = copy.deepcopy(self.lineage)
        duplicate["ticker_universe"][-1] = duplicate["ticker_universe"][-2]
        duplicate["ticker_universe_sha256"] = canonical_sha(duplicate["ticker_universe"])
        with self.assertRaises(PreregistrationError):
            self.bind(lineage_mapping=duplicate)

    def test_tampered_and_rehashed_immutable_audit_still_fails_semantics(self):
        audit = copy.deepcopy(self.immutable)
        audit["coverage"]["folds"] = 1
        self.resign_audit(audit)
        with self.assertRaises(PreregistrationError):
            self.bind(immutable_audit=audit)

    def test_rehashed_immutable_timestamp_cannot_replace_pinned_identity(self):
        audit = copy.deepcopy(self.immutable)
        audit["verified_at_utc"] = (self.completion + timedelta(minutes=11)).isoformat()
        self.resign_audit(audit)
        with self.assertRaises(PreregistrationError):
            self.bind(immutable_audit=audit)

    def test_tampered_and_rehashed_fresh_readback_still_fails_semantics(self):
        audit = copy.deepcopy(self.fresh)
        audit["source_artifacts"]["live_downstream_counts"]["model_runs"] = 1
        self.resign_audit(audit)
        with self.assertRaises(PreregistrationError):
            self.bind(fresh_readback_audit=audit)

    def test_rehashed_fresh_schema_presence_drift_fails_identity_match(self):
        audit = copy.deepcopy(self.fresh)
        audit["source_artifacts"]["live_downstream_schema_presence"]["model_runs"] = "present"
        self.resign_audit(audit)
        with self.assertRaises(PreregistrationError):
            self.bind(fresh_readback_audit=audit)

    def test_digest_substitution_and_wrong_executor_commit_fail(self):
        with self.assertRaises(PreregistrationError):
            self.bind(immutable_audit_file_sha256=self.immutable["audit_evidence_sha256"])
        final = copy.deepcopy(self.final)
        final["runtime"]["executor_git_commit"] = "5" * 40
        with self.assertRaises(PreregistrationError):
            self.bind(final_manifest=final)

    def test_rehashed_manifest_with_side_effect_or_wrong_universe_fails(self):
        final = copy.deepcopy(self.final)
        final["side_effects"]["orders"] = 1
        self.resign_final(final)
        immutable = copy.deepcopy(self.immutable)
        fresh = copy.deepcopy(self.fresh)
        for audit in (immutable, fresh):
            audit["source_artifacts"]["final_deterministic_evidence_sha256"] = final[
                "deterministic_evidence_sha256"]
            self.resign_audit(audit)
        with self.assertRaises(PreregistrationError):
            self.bind(final_manifest=final, immutable_audit=immutable,
                      fresh_readback_audit=fresh)
        final = copy.deepcopy(self.final)
        final["ticker_checkpoints"][0]["ticker"] = "ZZZ"
        self.resign_final(final)
        with self.assertRaises(PreregistrationError):
            self.bind(final_manifest=final)

    def test_calendar_slice_snapshot_commit_and_freshness_fail_closed(self):
        lineage = copy.deepcopy(self.lineage)
        lineage["sessions"][-416], lineage["sessions"][-415] = (
            lineage["sessions"][-415], lineage["sessions"][-416])
        lineage["sessions_sha256"] = canonical_sha(lineage["sessions"])
        with self.assertRaises(PreregistrationError):
            self.bind(lineage_mapping=lineage)
        lineage = dict(self.lineage, snapshot_sha256="a" * 64)
        with self.assertRaises(PreregistrationError):
            self.bind(lineage_mapping=lineage)
        with self.assertRaises(PreregistrationError):
            self.bind(current_model_git_commit="short")
        with self.assertRaises(PreregistrationError):
            self.bind(observed_at_utc=self.completion + timedelta(hours=2))

    def test_final_contract_audit_rejects_ready_and_sampler_attacks(self):
        manifest = self.bind()
        audit = manifest["baseline_audit"]
        fresh_at = self.completion + timedelta(minutes=20)
        proof_values = {
            "status": "VERIFIED", "baseline_manifest_sha256": audit["baseline_manifest_sha256"],
            "snapshot_id": audit["snapshot_id"], "snapshot_sha256": audit["snapshot_sha256"],
            "universe_id": audit["universe_id"], "universe_sha256": audit["universe_sha256"],
            "full_session_calendar_sha256": audit["full_session_calendar_sha256"],
            "model_session_dates_sha256": audit["model_session_dates_sha256"],
            "source_audit_artifact_sha256": audit["source_audit_artifact_sha256"],
            "embedded_audit_evidence_sha256": audit["embedded_audit_evidence_sha256"],
            "baseline_audit_sha256": audit["audit_sha256"],
            "source_readback_artifact_sha256": self.fresh_raw,
            "source_readback_embedded_evidence_sha256": self.fresh["audit_evidence_sha256"],
            "source_readback_observed_at_utc": fresh_at, "readback_at_utc": fresh_at,
            "ticker_count": 474, "fold_count": 1896, "oos_observation_count": 56880,
            "side_effects": dict(binding.ZERO_SIDE_EFFECTS),
            "downstream_counts": dict(binding.ZERO_DOWNSTREAM),
        }
        proof = BaselineReadbackProof(**proof_values)
        for mutation in ("ready", "sampler"):
            attacked = copy.deepcopy(manifest)
            if mutation == "ready":
                attacked["preflight"]["status"] = "READY"
                attacked["preflight"]["model_fit_authorized"] = True
            else:
                attacked["sampler_config"]["engine"] = "unsafe"
                attacked["lineage"]["sampler_sha256"] = canonical_sha(attacked["sampler_config"])
            payload = dict(attacked)
            payload.pop("checkpoint_identity_sha256")
            attacked["checkpoint_identity_sha256"] = canonical_sha(payload)
            with self.assertRaises(PreregistrationError):
                audit_preregistration_manifest(
                    attacked, observed_at_utc=self.observed, current_readback=proof)

    def test_no_callable_or_dataclass_exposes_operational_boundary(self):
        forbidden = {"ready", "order", "recommendation", "trade", "etf"}
        self.assertTrue(forbidden.isdisjoint(binding.__all__))
        self.assertEqual(binding.__all__, ["bind_verified_v4_baseline"])


if __name__ == "__main__":
    unittest.main()
