"""Corrected, pure Oracle research-dataset freeze-manifest builder.

This isolated v2 builder binds the independently verified bridge between the
legacy snapshot digest and the canonical Oracle JSONL provider digest.  It has
no connection, environment, write, schema, freeze, model, or trading surface.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import re


MANIFEST_CONTRACT = "oracle-research-dataset-freeze-manifest-v2"
CANONICAL_PROVIDER_SHA256 = "d0ae4b277bd63f8668fdb6898961bbb0b46f153c35fcb6bc15e8d1d616c23a1d"
LEGACY_PROVIDER_SHA256 = "7f92af47988d11251840b705c5dedf60cb88774aed73da8ba1a812d86195ab4a"
PROVIDER_BRIDGE_EVIDENCE_SHA256 = "34ad27e1defdf1f5333c8c7d044945383f60a826b4374ab6734af05dfcca37a3"
PROVIDER_ENCODING = "oracle-provider-lineage-jsonl-v1"
LEGACY_PROVIDER_ENCODING = "legacy-provider-lineage-compact-json-array-v1"

_APPROVAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}$")
_MISSING = frozenset({"missing", "none", "null", "tbd", "unknown"})
_VERIFIED_FIELDS = (
    ("market_snapshot_id", "market_features_2026-08-25_5b1044ee45605a3d"),
    ("market_snapshot_checksum_sha256", "5b1044ee45605a3d34eb459c2fdafb931da94f5dbe7b41adc8be8e303c5df011"),
    ("source_session_date", "2026-08-25"),
    ("first_session_date", "2021-09-08"),
    ("last_session_date", "2026-08-25"),
    ("expected_row_count", 586_710),
    ("expected_ticker_count", 474),
    ("expected_session_count", 1_246),
    ("expected_provider_lineage_count", 476),
    ("content_sha256", "07735e093c39546276082eba82f53a52d43a71cb1cff2d032b58f1315857a834"),
    ("ticker_universe_sha256", "267cdd0dba60a55346ba6f8a6e843259eacae924c9ea8740a093ea2cce3d1e26"),
    ("provider_lineage_sha256", CANONICAL_PROVIDER_SHA256),
    ("provider_lineage_encoding", PROVIDER_ENCODING),
    ("legacy_provider_lineage_sha256", LEGACY_PROVIDER_SHA256),
    ("legacy_provider_lineage_encoding", LEGACY_PROVIDER_ENCODING),
    ("provider_bridge_evidence_sha256", PROVIDER_BRIDGE_EVIDENCE_SHA256),
    ("source_snapshot_code_version", "1e28786832b633c8b63163e7954e3297b0b9ec0e"),
    ("model_screening_code_version", "2ef4a1082c91c023b9b0204611730492f03ad576"),
    ("content_encoding", "oracle-market-daily-features-jsonl-v1"),
    ("ticker_universe_encoding", "oracle-market-ticker-universe-jsonl-v1"),
    ("schema_version", "1"),
    ("operating_mode", "FROZEN/RESEARCH"),
)


class ManifestError(ValueError):
    pass


def canonical_sha256(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CorrectedFreezeManifest:
    dataset_version_id: str
    manifest_sha256: str
    schema_approval_id: str
    freeze_approval_id: str
    verified_fields: tuple[tuple[str, object], ...]

    def payload_without_hash(self) -> dict[str, object]:
        evidence = dict(self.verified_fields)
        return {
            "manifest_contract": MANIFEST_CONTRACT,
            "manifest_status": "REVIEW_ONLY/NOT_EXECUTABLE",
            "dataset_version_id": self.dataset_version_id,
            "dataset_identity": {
                key: evidence[key] for key in (
                    "market_snapshot_id", "market_snapshot_checksum_sha256",
                    "source_session_date", "first_session_date", "last_session_date",
                    "expected_row_count", "expected_ticker_count",
                    "expected_session_count", "expected_provider_lineage_count",
                    "content_sha256", "ticker_universe_sha256",
                    "provider_lineage_sha256", "schema_version",
                )
            },
            "code_lineage": {
                "source_snapshot_code_version": evidence["source_snapshot_code_version"],
                "model_screening_code_version": evidence["model_screening_code_version"],
            },
            "serialization": {
                "content_encoding": evidence["content_encoding"],
                "ticker_universe_encoding": evidence["ticker_universe_encoding"],
                "provider_lineage_encoding": evidence["provider_lineage_encoding"],
            },
            "provider_digest_bridge": {
                "evidence_sha256": evidence["provider_bridge_evidence_sha256"],
                "legacy_encoding": evidence["legacy_provider_lineage_encoding"],
                "legacy_sha256": evidence["legacy_provider_lineage_sha256"],
                "canonical_encoding": evidence["provider_lineage_encoding"],
                "canonical_sha256": evidence["provider_lineage_sha256"],
                "canonicalization_equivalent": True,
                "row_count": evidence["expected_provider_lineage_count"],
            },
            "governance": {
                "operating_mode": evidence["operating_mode"],
                "schema_approval_id": self.schema_approval_id,
                "freeze_approval_id": self.freeze_approval_id,
                "approvals_are_distinct": True,
            },
        }

    def to_dict(self) -> dict[str, object]:
        result = self.payload_without_hash()
        result["manifest_sha256"] = self.manifest_sha256
        return result


def verified_freeze_manifest_inputs() -> dict[str, object]:
    return dict(_VERIFIED_FIELDS)


def _approval(value: object, label: str) -> str:
    if (not isinstance(value, str) or not _APPROVAL_ID.fullmatch(value)
            or value.casefold() in _MISSING):
        raise ManifestError(f"{label} approval ID is missing or non-canonical")
    return value


def build_corrected_freeze_manifest(
    evidence: Mapping[str, object], *, schema_approval_id: str,
    freeze_approval_id: str,
) -> CorrectedFreezeManifest:
    if not isinstance(evidence, Mapping):
        raise ManifestError("freeze evidence must be a mapping")
    expected = dict(_VERIFIED_FIELDS)
    if set(evidence) != set(expected):
        raise ManifestError("freeze evidence keys differ from the exact v2 contract")
    for key, expected_value in _VERIFIED_FIELDS:
        if type(evidence[key]) is not type(expected_value) or evidence[key] != expected_value:
            raise ManifestError(f"freeze evidence mismatch for {key}")
    schema = _approval(schema_approval_id, "schema")
    freeze = _approval(freeze_approval_id, "freeze")
    if schema.casefold() == freeze.casefold():
        raise ManifestError("schema and freeze approvals must be distinct")
    identity_keys = (
        "market_snapshot_id", "market_snapshot_checksum_sha256",
        "source_session_date", "content_sha256", "ticker_universe_sha256",
        "provider_lineage_sha256",
    )
    identity_hash = canonical_sha256({key: expected[key] for key in identity_keys})
    dataset_id = f"oracle-research-{expected['source_session_date'].replace('-', '')}-{identity_hash[:32]}"
    provisional = CorrectedFreezeManifest(dataset_id, "", schema, freeze, _VERIFIED_FIELDS)
    manifest_hash = canonical_sha256(provisional.payload_without_hash())
    return CorrectedFreezeManifest(dataset_id, manifest_hash, schema, freeze, _VERIFIED_FIELDS)
