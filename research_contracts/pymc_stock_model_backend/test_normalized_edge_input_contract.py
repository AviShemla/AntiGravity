from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest

import numpy as np

try:
    from model_fit_contract_impl.execution_contract import PreregistrationProof
except ImportError:
    from research_contracts.stock_model_fit_execution.execution_contract import PreregistrationProof

try:
    from .normalized_edge_input_contract import (
        CLAIM_SCOPE,
        EXPECTED_FOLD_GEOMETRY,
        INPUT_CONTRACT_ID,
        NORMALIZED_EDGE_SOURCE_CONTRACT_ID,
        PREREGISTRATION_CONTRACT_ID,
        RETURN_UNIT,
        TOPOLOGY,
        FoldPayloadDescriptor,
        NormalizedEdge,
        NormalizedInputError,
        build_manifest,
        canonical_bytes,
        canonical_sha256,
        encode_fold_payload,
        load_verified_fold,
        serialize_manifest,
        verify_normalized_edge_bundle,
    )
except ImportError:  # isolated workspace execution
    from pymc_backend_runner_impl.normalized_edge_input_contract import (
    CLAIM_SCOPE,
    EXPECTED_FOLD_GEOMETRY,
    INPUT_CONTRACT_ID,
    NORMALIZED_EDGE_SOURCE_CONTRACT_ID,
    PREREGISTRATION_CONTRACT_ID,
    RETURN_UNIT,
    TOPOLOGY,
    FoldPayloadDescriptor,
    NormalizedEdge,
    NormalizedInputError,
    build_manifest,
    canonical_bytes,
    canonical_sha256,
    encode_fold_payload,
    load_verified_fold,
    serialize_manifest,
    verify_normalized_edge_bundle,
    )


NOW = datetime.now(timezone.utc)
TICKERS = tuple(f"T{index:03d}" for index in range(474))


def _prereg(**changes) -> PreregistrationProof:
    values = dict(
        contract_id=PREREGISTRATION_CONTRACT_ID,
        run_id="stock-prereg-fixture", raw_sha256="1" * 64,
        checkpoint_identity_sha256="2" * 64,
        independent_audit_raw_sha256="3" * 64,
        independent_audit_status="VERIFIED_FIXTURE_ONLY",
        independent_audit_observed_at_utc=NOW - timedelta(minutes=4),
        current_readback_raw_sha256="4" * 64,
        current_readback_status="VERIFIED_SELECT_ONLY",
        current_readback_observed_at_utc=NOW - timedelta(minutes=2),
        snapshot_id="market-features-fixture", snapshot_sha256="5" * 64,
        universe_id="approved-universe-fixture",
        universe_sha256=canonical_sha256(list(TICKERS)),
        full_session_calendar_sha256="7" * 64,
        model_session_dates_sha256="8" * 64,
        model_code_git_commit="b" * 40,
        model_config_sha256="9" * 64, sampler_sha256="c" * 64,
        candidate_lags=tuple(range(1, 8)), candidate_depths=tuple(range(1, 6)),
        target_count=474, fold_count=4, model_calendar_sessions=416,
        training_only_selection=True,
        multiple_testing_control="BH_FDR_PREREGISTERED",
        zero_temporal_overlap=True, fixture_only=True,
        model_fit_authorized=False, model_fit_started=False,
        downstream_counts={
            "predictions": 0, "recommendations": 0,
            "orders": 0, "etf_outputs": 0,
        },
    )
    values.update(changes)
    return PreregistrationProof(**values)


def _descriptor(target: str, fold: int, *, sha: str = "0" * 64, size: int = 9, **changes) -> FoldPayloadDescriptor:
    _, train_start, train_end, test_start, test_end = EXPECTED_FOLD_GEOMETRY[fold - 1]
    source = TICKERS[(TICKERS.index(target) + fold) % len(TICKERS)]
    values = dict(
        target_ticker=target,
        fold_number=fold,
        payload_key=f"folds/{target}/fold-{fold}.bin",
        payload_sha256=sha,
        payload_size_bytes=size,
        train_start_ordinal=train_start,
        train_end_ordinal=train_end,
        selection_end_ordinal=train_end,
        test_start_ordinal=test_start,
        test_end_ordinal=test_end,
        train_observations=289,
        test_observations=30,
        purge_sessions=7,
        selection_artifact_sha256=canonical_sha256({
            "target": target, "fold": fold, "selection_end": train_end,
            "source": source, "lag": fold + 1,
        }),
        edges=(NormalizedEdge(source_ticker=source, lag_sessions=fold + 1),),
    )
    values.update(changes)
    return FoldPayloadDescriptor(**values)


def _payload(record: FoldPayloadDescriptor, *, nonfinite: bool = False) -> bytes:
    depth = len(record.edges)
    x_train = np.zeros((289, depth), dtype=float)
    if nonfinite:
        x_train[0, 0] = np.nan
    return encode_fold_payload(
        record,
        x_train=x_train,
        y_train_direction=np.arange(289, dtype=np.uint8) % 2,
        y_train_return_pct=np.zeros(289),
        x_test=np.zeros((30, depth)),
        y_test_direction=np.arange(30, dtype=np.uint8) % 2,
        y_test_return_pct=np.zeros(30),
    )


class BundleFixture:
    def __init__(self):
        self.proof = _prereg()
        self.payloads: dict[str, bytes] = {}
        records = []
        for target in TICKERS:
            for fold in range(1, 5):
                temporary = _descriptor(target, fold)
                raw = _payload(temporary)
                record = replace(
                    temporary,
                    payload_sha256=hashlib.sha256(raw).hexdigest(),
                    payload_size_bytes=len(raw),
                )
                # SHA/size are not embedded in the payload header, so the same
                # bytes must decode against the finalized descriptor.
                self.payloads[record.payload_key] = raw
                records.append(record)
        self.manifest = build_manifest(
            contract_id=INPUT_CONTRACT_ID,
            preregistration_contract_id=PREREGISTRATION_CONTRACT_ID,
            preregistration_raw_sha256=self.proof.raw_sha256,
            checkpoint_identity_sha256=self.proof.checkpoint_identity_sha256,
            snapshot_id=self.proof.snapshot_id,
            snapshot_sha256=self.proof.snapshot_sha256,
            universe_id=self.proof.universe_id,
            universe_sha256=self.proof.universe_sha256,
            full_session_calendar_sha256=self.proof.full_session_calendar_sha256,
            model_session_dates_sha256=self.proof.model_session_dates_sha256,
            model_code_git_commit=self.proof.model_code_git_commit,
            model_config_sha256=self.proof.model_config_sha256,
            sampler_sha256=self.proof.sampler_sha256,
            normalized_edge_source_contract_id=NORMALIZED_EDGE_SOURCE_CONTRACT_ID,
            normalized_edge_source_sha256="d" * 64,
            multiple_testing_control=self.proof.multiple_testing_control,
            topology=TOPOLOGY,
            claim_scope=CLAIM_SCOPE,
            return_unit=RETURN_UNIT,
            candidate_lags=tuple(range(1, 8)),
            candidate_depths=tuple(range(1, 6)),
            calendar_sessions=416,
            target_count=474,
            fold_count=4,
            payload_count=1896,
            training_only_selection=True,
            zero_temporal_overlap=True,
            database_write_scope="NONE",
            downstream_counts={
                "predictions": 0, "recommendations": 0,
                "orders": 0, "etf_outputs": 0,
            },
            records=tuple(records),
        )
        self.raw = serialize_manifest(self.manifest)


class NormalizedEdgeInputContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = BundleFixture()

    def verify(self, *, raw=None, loader=None, proof=None):
        fixture = self.fixture
        return verify_normalized_edge_bundle(
            fixture.raw if raw is None else raw,
            payload_loader=(lambda key: fixture.payloads[key]) if loader is None else loader,
            preregistration=fixture.proof if proof is None else proof,
            observed_at_utc=NOW,
        )

    def rebuild(self, **changes):
        values = asdict(self.fixture.manifest)
        values.pop("deterministic_bundle_sha256")
        values.update(changes)
        return serialize_manifest(build_manifest(**values))

    def test_exact_474_by_4_bundle_passes(self):
        result = self.verify()
        self.assertEqual(result.target_count, 474)
        self.assertEqual(result.fold_count, 4)
        self.assertEqual(result.payload_count, 1896)
        self.assertEqual(result.verified_payload_count, 1896)
        self.assertEqual(result.database_writes, 0)
        self.assertEqual(result.downstream_outputs, 0)

    def test_verified_fold_is_rehashed_and_decoded(self):
        bundle = self.verify()
        payload = load_verified_fold(
            bundle, target_ticker="T000", fold_number=1,
            payload_loader=lambda key: self.fixture.payloads[key],
        )
        self.assertEqual(payload.x_train.shape, (289, 1))
        self.assertEqual(payload.x_test.shape, (30, 1))
        self.assertEqual(payload.train_session_ordinals[0], 0)
        self.assertEqual(payload.test_session_ordinals[0], 296)

    def test_payload_tamper_is_rejected(self):
        first_key = self.fixture.manifest.records[0].payload_key
        def loader(key):
            raw = self.fixture.payloads[key]
            return raw[:-1] + bytes([raw[-1] ^ 1]) if key == first_key else raw
        with self.assertRaisesRegex(NormalizedInputError, "SHA-256 differs"):
            self.verify(loader=loader)

    def test_missing_payload_is_rejected(self):
        first_key = self.fixture.manifest.records[0].payload_key
        def loader(key):
            if key == first_key:
                raise KeyError(key)
            return self.fixture.payloads[key]
        with self.assertRaisesRegex(NormalizedInputError, "unavailable"):
            self.verify(loader=loader)

    def test_incomplete_record_coverage_is_rejected_before_fit(self):
        records = self.fixture.manifest.records[:-1]
        raw = self.rebuild(records=records)
        with self.assertRaisesRegex(NormalizedInputError, "record coverage is incomplete"):
            self.verify(raw=raw)

    def test_duplicate_target_fold_is_rejected(self):
        records = list(self.fixture.manifest.records)
        records[-1] = records[-2]
        raw = self.rebuild(records=tuple(records))
        with self.assertRaisesRegex(NormalizedInputError, "duplicated or unsorted"):
            self.verify(raw=raw)

    def test_purge_overlap_is_rejected(self):
        records = list(self.fixture.manifest.records)
        records[0] = replace(records[0], test_start_ordinal=295)
        raw = self.rebuild(records=tuple(records))
        with self.assertRaisesRegex(NormalizedInputError, "geometry differs"):
            self.verify(raw=raw)

    def test_selection_after_training_is_rejected(self):
        records = list(self.fixture.manifest.records)
        records[0] = replace(records[0], selection_end_ordinal=289)
        raw = self.rebuild(records=tuple(records))
        with self.assertRaisesRegex(NormalizedInputError, "selection, purge"):
            self.verify(raw=raw)

    def test_selection_artifact_tamper_is_rejected(self):
        records = list(self.fixture.manifest.records)
        records[0] = replace(records[0], selection_artifact_sha256="not-a-sha")
        raw = self.rebuild(records=tuple(records))
        with self.assertRaisesRegex(NormalizedInputError, "selection artifact"):
            self.verify(raw=raw)

    def test_source_outside_s07_universe_is_rejected(self):
        records = list(self.fixture.manifest.records)
        record = records[0]
        external = replace(record, edges=(NormalizedEdge("OUTSIDE", 2),))
        payload = _payload(external)
        external = replace(
            external, payload_sha256=hashlib.sha256(payload).hexdigest(),
            payload_size_bytes=len(payload),
        )
        records[0] = external
        raw = self.rebuild(records=tuple(records))
        def loader(key):
            return payload if key == external.payload_key else self.fixture.payloads[key]
        with self.assertRaisesRegex(NormalizedInputError, "outside the S07 universe"):
            self.verify(raw=raw, loader=loader)

    def test_s07_hash_mismatch_is_rejected(self):
        with self.assertRaisesRegex(NormalizedInputError, "exact S07 lineage"):
            self.verify(proof=replace(self.fixture.proof, sampler_sha256="d" * 64))

    def test_s07_stale_readback_is_rejected(self):
        stale = replace(
            self.fixture.proof,
            current_readback_observed_at_utc=NOW - timedelta(hours=2),
        )
        with self.assertRaisesRegex(NormalizedInputError, "stale"):
            self.verify(proof=stale)

    def test_s07_authorizing_state_is_rejected(self):
        with self.assertRaisesRegex(NormalizedInputError, "geometry or side-effect"):
            self.verify(proof=replace(self.fixture.proof, model_fit_authorized=True))

    def test_manifest_tamper_without_rehash_is_rejected(self):
        value = json.loads(self.fixture.raw)
        value["return_unit"] = "DECIMAL"
        raw = canonical_bytes(value) + b"\n"
        with self.assertRaisesRegex(NormalizedInputError, "geometry or safety"):
            self.verify(raw=raw)

    def test_manifest_deterministic_hash_tamper_is_rejected(self):
        value = json.loads(self.fixture.raw)
        value["deterministic_bundle_sha256"] = "f" * 64
        raw = canonical_bytes(value) + b"\n"
        with self.assertRaisesRegex(NormalizedInputError, "deterministic identity"):
            self.verify(raw=raw)

    def test_universe_hash_mismatch_is_rejected(self):
        raw = self.rebuild(universe_sha256="e" * 64)
        with self.assertRaisesRegex(NormalizedInputError, "exact S07 lineage"):
            self.verify(raw=raw)

    def test_unsafe_payload_key_is_rejected(self):
        records = list(self.fixture.manifest.records)
        records[0] = replace(records[0], payload_key="../escape.bin")
        raw = self.rebuild(records=tuple(records))
        with self.assertRaisesRegex(NormalizedInputError, "key differs or is unsafe"):
            self.verify(raw=raw)

    def test_payload_with_nonfinite_numeric_value_is_rejected_even_when_rehashed(self):
        record = self.fixture.manifest.records[0]
        raw = bytearray(self.fixture.payloads[record.payload_key])
        # First x_train float begins immediately after the canonical header.
        header_length = int.from_bytes(raw[:8], "big")
        offset = 8 + header_length
        raw[offset:offset + 8] = np.asarray([np.nan], dtype="<f8").tobytes()
        changed = bytes(raw)
        records = list(self.fixture.manifest.records)
        records[0] = replace(
            record, payload_sha256=hashlib.sha256(changed).hexdigest(),
            payload_size_bytes=len(changed),
        )
        manifest_raw = self.rebuild(records=tuple(records))
        def loader(key):
            return changed if key == record.payload_key else self.fixture.payloads[key]
        with self.assertRaisesRegex(NormalizedInputError, "non-finite"):
            self.verify(raw=manifest_raw, loader=loader)

    def test_reloading_verified_fold_rejects_later_source_change(self):
        bundle = self.verify()
        key = self.fixture.manifest.records[0].payload_key
        def loader(candidate):
            raw = self.fixture.payloads[candidate]
            return raw + b"x" if candidate == key else raw
        with self.assertRaisesRegex(NormalizedInputError, "size differs"):
            load_verified_fold(
                bundle, target_ticker="T000", fold_number=1,
                payload_loader=loader,
            )


if __name__ == "__main__":
    unittest.main()
