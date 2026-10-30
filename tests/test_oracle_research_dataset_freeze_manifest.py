import hashlib
import json
import unittest
from dataclasses import FrozenInstanceError

from model_lineage import LineageError
from oracle_research_dataset_freeze_manifest import (
    MANIFEST_CONTRACT,
    build_oracle_research_dataset_freeze_manifest,
    verified_freeze_manifest_inputs,
)


SCHEMA_APPROVAL = "schema-approval-20260826"
FREEZE_APPROVAL = "freeze-approval-20260826"


def build(evidence=None, **approvals):
    return build_oracle_research_dataset_freeze_manifest(
        verified_freeze_manifest_inputs() if evidence is None else evidence,
        schema_approval_id=approvals.get("schema_approval_id", SCHEMA_APPROVAL),
        freeze_approval_id=approvals.get("freeze_approval_id", FREEZE_APPROVAL),
    )


class OracleResearchDatasetFreezeManifestTests(unittest.TestCase):
    def test_exact_verified_identity_is_bound_without_execution_fields(self):
        manifest = build().to_dict()
        self.assertEqual(manifest["manifest_contract"], MANIFEST_CONTRACT)
        self.assertEqual(manifest["manifest_status"], "REVIEW_ONLY/NOT_EXECUTABLE")
        self.assertEqual(
            manifest["dataset_identity"],
            {
                "market_snapshot_id": "market_features_2026-08-25_5b1044ee45605a3d",
                "market_snapshot_checksum_sha256": "5b1044ee45605a3d34eb459c2fdafb931da94f5dbe7b41adc8be8e303c5df011",
                "source_session_date": "2026-08-25",
                "first_session_date": "2021-09-08",
                "last_session_date": "2026-08-25",
                "expected_row_count": 586_710,
                "expected_ticker_count": 474,
                "expected_session_count": 1_246,
                "expected_provider_lineage_count": 476,
                "content_sha256": "07735e093c39546276082eba82f53a52d43a71cb1cff2d032b58f1315857a834",
                "ticker_universe_sha256": "267cdd0dba60a55346ba6f8a6e843259eacae924c9ea8740a093ea2cce3d1e26",
                "provider_lineage_sha256": "7f92af47988d11251840b705c5dedf60cb88774aed73da8ba1a812d86195ab4a",
                "schema_version": "1",
            },
        )
        self.assertEqual(
            manifest["code_lineage"],
            {
                "source_snapshot_code_version": "1e28786832b633c8b63163e7954e3297b0b9ec0e",
                "model_screening_code_version": "2ef4a1082c91c023b9b0204611730492f03ad576",
            },
        )
        self.assertEqual(
            manifest["serialization"],
            {
                "content_encoding": "oracle-market-daily-features-jsonl-v1",
                "ticker_universe_encoding": "oracle-market-ticker-universe-jsonl-v1",
            },
        )
        self.assertEqual(
            manifest["governance"],
            {
                "operating_mode": "FROZEN/RESEARCH",
                "schema_approval_id": SCHEMA_APPROVAL,
                "freeze_approval_id": FREEZE_APPROVAL,
                "approvals_are_distinct": True,
            },
        )

    def test_dataset_version_and_manifest_hashes_are_deterministic_and_recomputable(self):
        first = build()
        second = build()
        self.assertEqual(first, second)
        document = first.to_dict()
        claimed = document.pop("manifest_sha256")
        canonical = json.dumps(
            document,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        self.assertEqual(claimed, hashlib.sha256(canonical).hexdigest())
        self.assertEqual(first.manifest_sha256, claimed)
        self.assertEqual(
            first.dataset_version_id,
            "oracle-research-20260825-60f2d9d6f68d7d7d9930abce00d4ba41",
        )
        self.assertEqual(
            first.manifest_sha256,
            "cbdf13a70b0aa578ade5d8fff5050274a78fa0b0d7b3a0a5679e14276b861894",
        )

    def test_approval_changes_manifest_hash_but_not_dataset_identity(self):
        first = build()
        second = build(freeze_approval_id="freeze-approval-20260826-v2")
        self.assertEqual(first.dataset_version_id, second.dataset_version_id)
        self.assertNotEqual(first.manifest_sha256, second.manifest_sha256)

    def test_result_is_frozen_and_serialization_is_detached(self):
        manifest = build()
        with self.assertRaises(FrozenInstanceError):
            manifest.dataset_version_id = "changed"
        document = manifest.to_dict()
        document["dataset_identity"]["expected_row_count"] = 1
        self.assertEqual(manifest.to_dict()["dataset_identity"]["expected_row_count"], 586_710)

    def test_every_verified_value_mismatch_fails_closed(self):
        baseline = verified_freeze_manifest_inputs()
        for key, value in baseline.items():
            changed = dict(baseline)
            changed[key] = value + 1 if isinstance(value, int) else f"{value}-mismatch"
            with self.subTest(key=key), self.assertRaisesRegex(LineageError, "mismatch"):
                build(changed)

    def test_missing_extra_and_downstream_fields_are_rejected(self):
        baseline = verified_freeze_manifest_inputs()
        missing = dict(baseline)
        missing.pop("content_sha256")
        with self.assertRaisesRegex(LineageError, "missing"):
            build(missing)
        for field in (
            "model_output",
            "prediction",
            "etf_prior",
            "recommendation",
            "order",
            "trading_enabled",
        ):
            changed = dict(baseline)
            changed[field] = True
            with self.subTest(field=field), self.assertRaisesRegex(LineageError, "undeclared"):
                build(changed)

    def test_missing_noncanonical_or_same_approval_ids_are_rejected(self):
        invalid = (
            "",
            " x",
            "x ",
            "x",
            "contains space",
            "MISSING",
            "none",
            "TBD",
            "unknown",
            None,
        )
        for value in invalid:
            with self.subTest(schema=value), self.assertRaises(LineageError):
                build(schema_approval_id=value)
            with self.subTest(freeze=value), self.assertRaises(LineageError):
                build(freeze_approval_id=value)
        with self.assertRaisesRegex(LineageError, "distinct"):
            build(freeze_approval_id=SCHEMA_APPROVAL.upper())

    def test_non_frozen_mode_and_non_mapping_evidence_are_rejected(self):
        changed = verified_freeze_manifest_inputs()
        changed["operating_mode"] = "PAPER-MANUAL"
        with self.assertRaisesRegex(LineageError, "operating_mode"):
            build(changed)
        with self.assertRaisesRegex(LineageError, "mapping"):
            build([])


if __name__ == "__main__":
    unittest.main()
