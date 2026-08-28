from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import audit_only_baseline_v2 as subject


def cj(value: object) -> bytes:
    return subject.canonical_bytes(value)


class MiniSemantic:
    PRODUCER_CONTRACT_ID = subject.PRODUCER_CONTRACT_ID

    @staticmethod
    def decode_json(raw: bytes) -> object:
        return subject.decode_json(raw, "semantic input")

    @staticmethod
    def validate_manifest(payload, checkpoints, executor_git_commit, sessions, *, verified_at):
        if executor_git_commit != "a" * 40 or tuple(sessions) != ("2026-08-24", "2026-08-25"):
            raise subject.AuditV2Error("semantic lineage differs")
        if set(checkpoints) != {"AAA", "BBB"}:
            raise subject.AuditV2Error("semantic checkpoint set differs")
        return {"coverage": {"tickers": 2, "folds": 8, "oos_observations": 240}}


def fixture() -> dict[str, object]:
    commit = "a" * 40
    checkpoints: dict[str, bytes] = {}
    entries = []
    for ticker in ("AAA", "BBB"):
        payload = {"ticker": ticker}
        digest = subject.sha256(cj(payload))
        payload["checkpoint_sha256"] = digest
        body = cj(payload)
        checkpoints[ticker] = body
        entries.append({"ticker": ticker, "checkpoint_sha256": digest})
    deterministic = {
        "contract_id": subject.PRODUCER_CONTRACT_ID,
        "lineage_sha256": "b" * 64,
        "coverage": {"tickers": 2, "folds": 8, "oos_observations": 240},
        "aggregate": {},
        "ticker_checkpoints": entries,
        "side_effects": dict(subject.ZERO_SIDE_EFFECTS),
    }
    deterministic_sha = subject.sha256(cj(deterministic))
    manifest = {
        **deterministic,
        "deterministic_evidence_sha256": deterministic_sha,
        "runtime": {"executor_git_commit": commit, "observed_at_utc": "2026-08-27T01:29:57Z"},
    }
    executor = {"executor_git_commit": commit, "artifacts": {"producer.py": "c" * 64}}
    executor_bytes = cj(executor)
    manifest_bytes = cj(manifest)
    pins = subject.ProducerPins(
        git_commit=commit,
        manifest_sha256=subject.sha256(manifest_bytes),
        executor_sha256=subject.sha256(executor_bytes),
        deterministic_sha256=deterministic_sha,
        lineage_sha256="b" * 64,
        tickers=2,
        folds=8,
        oos_observations=240,
    )
    release = {
        "contract_id": subject.CONTRACT_ID,
        "verifier_git_commit": "d" * 40,
        "producer_binding": {
            "git_commit": pins.git_commit,
            "manifest_sha256": pins.manifest_sha256,
            "executor_sha256": pins.executor_sha256,
            "deterministic_sha256": pins.deterministic_sha256,
        },
        "artifacts": {
            "audit_only_baseline_v2.py": "1" * 64,
            "audit_full_universe_simple_baselines.py": "2" * 64,
            "test_audit_only_baseline_v2.py": "3" * 64,
        },
        "read_scope": "EXACT_THREE_SELECTS_FINAL_PHASE_ONLY",
        "write_scope": "NONE",
        "execution_authorized": False,
    }
    release_bytes = cj(release)
    named = {subject._checkpoint_name(ticker): raw for ticker, raw in checkpoints.items()}
    return {
        "pins": pins,
        "executor": executor_bytes,
        "manifest": manifest_bytes,
        "checkpoints": named,
        "release": release_bytes,
        "release_sha": subject.sha256(release_bytes),
    }


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixture()

    def verify(self):
        return subject.verify_offline_artifacts(
            producer_executor_bytes=self.fx["executor"],
            producer_manifest_bytes=self.fx["manifest"],
            checkpoint_files=self.fx["checkpoints"],
            verifier_release_manifest_bytes=self.fx["release"],
            expected_verifier_release_manifest_sha256=self.fx["release_sha"],
            pins=self.fx["pins"],
        )

    def test_offline_identity_phase_separates_producer_and_verifier(self):
        proof = self.verify()
        self.assertEqual(proof.producer_git_commit, "a" * 40)
        self.assertEqual(proof.verifier_git_commit, "d" * 40)
        self.assertFalse(proof.execution_authorized)
        self.assertFalse(proof.live_readback_complete)
        self.assertEqual(proof.checkpoint_count, 2)

    def test_manifest_byte_tamper_fails_even_if_json_still_parses(self):
        self.fx["manifest"] += b" "
        with self.assertRaisesRegex(subject.AuditV2Error, "manifest bytes"):
            self.verify()

    def test_executor_byte_tamper_fails(self):
        self.fx["executor"] += b"\n"
        with self.assertRaisesRegex(subject.AuditV2Error, "executor bytes"):
            self.verify()

    def test_external_release_pin_cannot_be_ignored(self):
        self.fx["release_sha"] = "0" * 64
        with self.assertRaisesRegex(subject.AuditV2Error, "external pin"):
            self.verify()

    def test_producer_and_verifier_commit_cannot_be_conflated(self):
        release = subject.decode_json(self.fx["release"], "release")
        release["verifier_git_commit"] = self.fx["pins"].git_commit
        self.fx["release"] = cj(release)
        self.fx["release_sha"] = subject.sha256(self.fx["release"])
        with self.assertRaisesRegex(subject.AuditV2Error, "conflated"):
            self.verify()

    def test_coherent_producer_rehash_still_fails_pinned_manifest(self):
        manifest = subject.decode_json(self.fx["manifest"], "manifest")
        manifest["side_effects"]["predictions"] = 1
        self.fx["manifest"] = cj(manifest)
        with self.assertRaisesRegex(subject.AuditV2Error, "manifest bytes"):
            self.verify()

    def test_missing_checkpoint_fails(self):
        self.fx["checkpoints"].pop(next(iter(self.fx["checkpoints"])))
        with self.assertRaisesRegex(subject.AuditV2Error, "checkpoint file digest"):
            self.verify()

    def test_extra_checkpoint_fails(self):
        self.fx["checkpoints"]["ticker-extra.json"] = b"{}"
        with self.assertRaisesRegex(subject.AuditV2Error, "missing or extra"):
            self.verify()

    def test_checkpoint_payload_tamper_fails(self):
        name = next(iter(self.fx["checkpoints"]))
        value = subject.decode_json(self.fx["checkpoints"][name], "checkpoint")
        value["ticker"] = "ATTACK"
        self.fx["checkpoints"][name] = cj(value)
        with self.assertRaisesRegex(subject.AuditV2Error, "checkpoint ticker payload"):
            self.verify()

    def test_release_artifact_closure_is_exact(self):
        release = subject.decode_json(self.fx["release"], "release")
        release["artifacts"]["unbound.py"] = "4" * 64
        self.fx["release"] = cj(release)
        self.fx["release_sha"] = subject.sha256(self.fx["release"])
        with self.assertRaisesRegex(subject.AuditV2Error, "artifact closure"):
            self.verify()

    def test_release_cannot_authorize_execution(self):
        release = subject.decode_json(self.fx["release"], "release")
        release["execution_authorized"] = True
        self.fx["release"] = cj(release)
        self.fx["release_sha"] = subject.sha256(self.fx["release"])
        with self.assertRaisesRegex(subject.AuditV2Error, "authority boundary"):
            self.verify()

    def test_release_builder_is_deterministic_and_non_authorizing(self):
        kwargs = {
            "verifier_git_commit": "d" * 40,
            "verifier_module_bytes": b"module",
            "semantic_auditor_bytes": b"semantic",
            "verifier_test_bytes": b"tests",
            "pins": self.fx["pins"],
        }
        first = subject.build_verifier_release_manifest(**kwargs)
        second = subject.build_verifier_release_manifest(**kwargs)
        self.assertEqual(first, second)
        release = subject.decode_json(first, "release")
        self.assertFalse(release["execution_authorized"])
        self.assertEqual(release["write_scope"], "NONE")

    def test_release_builder_rejects_producer_commit_and_missing_bytes(self):
        with self.assertRaisesRegex(subject.AuditV2Error, "integration commit"):
            subject.build_verifier_release_manifest(
                verifier_git_commit=self.fx["pins"].git_commit,
                verifier_module_bytes=b"module",
                semantic_auditor_bytes=b"semantic",
                verifier_test_bytes=b"tests",
                pins=self.fx["pins"],
            )
        with self.assertRaisesRegex(subject.AuditV2Error, "bytes are absent"):
            subject.build_verifier_release_manifest(
                verifier_git_commit="d" * 40,
                verifier_module_bytes=b"",
                semantic_auditor_bytes=b"semantic",
                verifier_test_bytes=b"tests",
                pins=self.fx["pins"],
            )


class LiveFinalizationTests(BoundaryTests):
    def live(self) -> subject.LiveReadback:
        return subject.LiveReadback(
            observed_at_utc="2026-08-27T02:00:00+00:00",
            effective_identity=subject.EXPECTED_EFFECTIVE_IDENTITY,
            database_name="theoracle",
            snapshot_id=subject.SNAPSHOT_ID,
            source_session_date=subject.SOURCE_SESSION_DATE,
            sessions=("2026-08-24", "2026-08-25"),
            session_sha256=subject.sha256(cj(["2026-08-24", "2026-08-25"])),
            downstream_counts={name: 0 for name in subject.DOWNSTREAM_NAMES},
            select_statement_count=3,
            database_write_count=0,
        )

    def finalize(self, live=None):
        proof = self.verify()
        old_count, old_sha = subject.EXPECTED_SESSIONS, subject.SESSION_SHA256
        subject.EXPECTED_SESSIONS = 2
        subject.SESSION_SHA256 = subject.sha256(cj(["2026-08-24", "2026-08-25"]))
        try:
            return subject.finalize_live_audit(
                offline=proof,
                producer_executor_bytes=self.fx["executor"],
                producer_manifest_bytes=self.fx["manifest"],
                checkpoint_files=self.fx["checkpoints"],
                verifier_release_manifest_bytes=self.fx["release"],
                expected_verifier_release_manifest_sha256=self.fx["release_sha"],
                live=live or self.live(),
                finalized_at_utc="2026-08-27T02:01:00+00:00",
                semantic_verifier=MiniSemantic(),
                pins=self.fx["pins"],
            )
        finally:
            subject.EXPECTED_SESSIONS, subject.SESSION_SHA256 = old_count, old_sha

    def test_exact_three_select_evidence_can_finalize(self):
        evidence = self.finalize()
        self.assertEqual(evidence["stage"], "VERIFIED")
        self.assertFalse(evidence["execution_authorized"])
        self.assertFalse(evidence["successor_authorized"])
        self.assertEqual(evidence["coverage"]["oos_observations"], 240)

    def test_two_or_four_selects_fail(self):
        for count in (2, 4):
            with self.subTest(count=count), self.assertRaisesRegex(
                subject.AuditV2Error, "three-SELECT"
            ):
                self.finalize(replace(self.live(), select_statement_count=count))

    def test_any_database_write_fails(self):
        with self.assertRaisesRegex(subject.AuditV2Error, "three-SELECT"):
            self.finalize(replace(self.live(), database_write_count=1))

    def test_wrong_database_or_identity_fails(self):
        for live in (
            replace(self.live(), database_name="rehearsal"),
            replace(self.live(), effective_identity=""),
        ):
            with self.subTest(live=live), self.assertRaisesRegex(
                subject.AuditV2Error, "three-SELECT"
            ):
                self.finalize(live)

    def test_wrong_calendar_hash_or_order_fails(self):
        for live in (
            replace(self.live(), session_sha256="0" * 64),
            replace(self.live(), sessions=("2026-08-25", "2026-08-24")),
        ):
            with self.subTest(live=live), self.assertRaisesRegex(
                subject.AuditV2Error, "three-SELECT"
            ):
                self.finalize(live)

    def test_nonzero_downstream_count_fails(self):
        counts = dict(self.live().downstream_counts)
        counts["model_runs"] = 1
        with self.assertRaisesRegex(subject.AuditV2Error, "three-SELECT"):
            self.finalize(replace(self.live(), downstream_counts=counts))

    def test_missing_downstream_table_evidence_fails(self):
        counts = dict(self.live().downstream_counts)
        counts.pop("etf_prior_lineage")
        with self.assertRaisesRegex(subject.AuditV2Error, "three-SELECT"):
            self.finalize(replace(self.live(), downstream_counts=counts))

    def test_naive_timestamp_fails(self):
        with self.assertRaisesRegex(subject.AuditV2Error, "timezone-aware"):
            self.finalize(replace(self.live(), observed_at_utc="2026-08-27T02:00:00"))

    def test_semantic_verifier_cannot_change_coverage(self):
        class Bad(MiniSemantic):
            @staticmethod
            def validate_manifest(*args, **kwargs):
                return {"coverage": {"tickers": 1, "folds": 8, "oos_observations": 240}}

        proof = self.verify()
        old_count, old_sha = subject.EXPECTED_SESSIONS, subject.SESSION_SHA256
        subject.EXPECTED_SESSIONS = 2
        subject.SESSION_SHA256 = subject.sha256(cj(["2026-08-24", "2026-08-25"]))
        try:
            with self.assertRaisesRegex(subject.AuditV2Error, "coverage differs"):
                subject.finalize_live_audit(
                    offline=proof,
                    producer_executor_bytes=self.fx["executor"],
                    producer_manifest_bytes=self.fx["manifest"],
                    checkpoint_files=self.fx["checkpoints"],
                    verifier_release_manifest_bytes=self.fx["release"],
                    expected_verifier_release_manifest_sha256=self.fx["release_sha"],
                    live=self.live(),
                    finalized_at_utc="2026-08-27T02:01:00+00:00",
                    semantic_verifier=Bad(),
                    pins=self.fx["pins"],
                )
        finally:
            subject.EXPECTED_SESSIONS, subject.SESSION_SHA256 = old_count, old_sha

    def test_forged_offline_proof_fails_replay(self):
        proof = replace(self.verify(), checkpoint_count=999)
        old_count, old_sha = subject.EXPECTED_SESSIONS, subject.SESSION_SHA256
        subject.EXPECTED_SESSIONS = 2
        subject.SESSION_SHA256 = subject.sha256(cj(["2026-08-24", "2026-08-25"]))
        try:
            with self.assertRaisesRegex(subject.AuditV2Error, "does not replay"):
                subject.finalize_live_audit(
                    offline=proof,
                    producer_executor_bytes=self.fx["executor"],
                    producer_manifest_bytes=self.fx["manifest"],
                    checkpoint_files=self.fx["checkpoints"],
                    verifier_release_manifest_bytes=self.fx["release"],
                    expected_verifier_release_manifest_sha256=self.fx["release_sha"],
                    live=self.live(),
                    finalized_at_utc="2026-08-27T02:01:00+00:00",
                    semantic_verifier=MiniSemantic(),
                    pins=self.fx["pins"],
                )
        finally:
            subject.EXPECTED_SESSIONS, subject.SESSION_SHA256 = old_count, old_sha

    def test_stale_or_reversed_live_chronology_fails(self):
        for finalized in ("2026-08-27T01:59:59+00:00", "2026-08-27T02:06:00+00:00"):
            proof = self.verify()
            old_count, old_sha = subject.EXPECTED_SESSIONS, subject.SESSION_SHA256
            subject.EXPECTED_SESSIONS = 2
            subject.SESSION_SHA256 = subject.sha256(cj(["2026-08-24", "2026-08-25"]))
            try:
                with self.subTest(finalized=finalized), self.assertRaisesRegex(
                    subject.AuditV2Error, "chronology or freshness"
                ):
                    subject.finalize_live_audit(
                        offline=proof,
                        producer_executor_bytes=self.fx["executor"],
                        producer_manifest_bytes=self.fx["manifest"],
                        checkpoint_files=self.fx["checkpoints"],
                        verifier_release_manifest_bytes=self.fx["release"],
                        expected_verifier_release_manifest_sha256=self.fx["release_sha"],
                        live=self.live(),
                        finalized_at_utc=finalized,
                        semantic_verifier=MiniSemantic(),
                        pins=self.fx["pins"],
                    )
            finally:
                subject.EXPECTED_SESSIONS, subject.SESSION_SHA256 = old_count, old_sha


if __name__ == "__main__":
    unittest.main()
