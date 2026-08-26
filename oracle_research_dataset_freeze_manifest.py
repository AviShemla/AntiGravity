"""Pure fail-closed builder for one immutable Oracle freeze manifest.

This module owns no connection, environment, schema, write, freeze, model, ETF,
recommendation, order, or trading behavior.  It only validates the exact
verified research-dataset identity and returns an immutable manifest value.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from model_lineage import LineageError
from oracle_research_dataset_serializers import (
    MARKET_CONTENT_ENCODING,
    TICKER_UNIVERSE_ENCODING,
)


MANIFEST_CONTRACT = "oracle-research-dataset-freeze-manifest-v1"
_APPROVAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}$")
_MISSING_APPROVAL_SENTINELS = frozenset({"missing", "none", "null", "tbd", "unknown"})
_VERIFIED_FIELDS = (
    ("market_snapshot_id", "market_features_2026-08-25_5b1044ee45605a3d"),
    (
        "market_snapshot_checksum_sha256",
        "5b1044ee45605a3d34eb459c2fdafb931da94f5dbe7b41adc8be8e303c5df011",
    ),
    ("source_session_date", "2026-08-25"),
    ("first_session_date", "2021-09-08"),
    ("last_session_date", "2026-08-25"),
    ("expected_row_count", 586_710),
    ("expected_ticker_count", 474),
    ("expected_session_count", 1_246),
    ("expected_provider_lineage_count", 476),
    (
        "content_sha256",
        "07735e093c39546276082eba82f53a52d43a71cb1cff2d032b58f1315857a834",
    ),
    (
        "ticker_universe_sha256",
        "267cdd0dba60a55346ba6f8a6e843259eacae924c9ea8740a093ea2cce3d1e26",
    ),
    (
        "provider_lineage_sha256",
        "7f92af47988d11251840b705c5dedf60cb88774aed73da8ba1a812d86195ab4a",
    ),
    ("source_snapshot_code_version", "1e28786832b633c8b63163e7954e3297b0b9ec0e"),
    ("model_screening_code_version", "2ef4a1082c91c023b9b0204611730492f03ad576"),
    ("content_encoding", MARKET_CONTENT_ENCODING),
    ("ticker_universe_encoding", TICKER_UNIVERSE_ENCODING),
    ("schema_version", "1"),
    ("operating_mode", "FROZEN/RESEARCH"),
)


@dataclass(frozen=True)
class OracleResearchDatasetFreezeManifest:
    """Immutable result; ``to_dict`` returns a detached serialization copy."""

    dataset_version_id: str
    manifest_sha256: str
    schema_approval_id: str
    freeze_approval_id: str
    verified_fields: tuple[tuple[str, object], ...]

    def _payload_without_hash(self) -> dict[str, object]:
        evidence = dict(self.verified_fields)
        return {
            "manifest_contract": MANIFEST_CONTRACT,
            "manifest_status": "REVIEW_ONLY/NOT_EXECUTABLE",
            "dataset_version_id": self.dataset_version_id,
            "dataset_identity": {
                key: evidence[key]
                for key in (
                    "market_snapshot_id",
                    "market_snapshot_checksum_sha256",
                    "source_session_date",
                    "first_session_date",
                    "last_session_date",
                    "expected_row_count",
                    "expected_ticker_count",
                    "expected_session_count",
                    "expected_provider_lineage_count",
                    "content_sha256",
                    "ticker_universe_sha256",
                    "provider_lineage_sha256",
                    "schema_version",
                )
            },
            "code_lineage": {
                "source_snapshot_code_version": evidence["source_snapshot_code_version"],
                "model_screening_code_version": evidence["model_screening_code_version"],
            },
            "serialization": {
                "content_encoding": evidence["content_encoding"],
                "ticker_universe_encoding": evidence["ticker_universe_encoding"],
            },
            "governance": {
                "operating_mode": evidence["operating_mode"],
                "schema_approval_id": self.schema_approval_id,
                "freeze_approval_id": self.freeze_approval_id,
                "approvals_are_distinct": True,
            },
        }

    def to_dict(self) -> dict[str, object]:
        payload = self._payload_without_hash()
        payload["manifest_sha256"] = self.manifest_sha256
        return payload


def verified_freeze_manifest_inputs() -> dict[str, object]:
    """Return a detached copy of the exact verified input contract."""

    return dict(_VERIFIED_FIELDS)


def _canonical_sha256(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _approval(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not _APPROVAL_ID.fullmatch(value)
        or value.casefold() in _MISSING_APPROVAL_SENTINELS
    ):
        raise LineageError(f"{label} approval ID is missing or non-canonical.")
    return value


def build_oracle_research_dataset_freeze_manifest(
    evidence: Mapping[str, object],
    *,
    schema_approval_id: str,
    freeze_approval_id: str,
) -> OracleResearchDatasetFreezeManifest:
    """Validate exact evidence and build one deterministic immutable manifest."""

    if not isinstance(evidence, Mapping):
        raise LineageError("Freeze-manifest evidence must be a mapping.")
    expected = dict(_VERIFIED_FIELDS)
    supplied_keys = set(evidence)
    expected_keys = set(expected)
    if supplied_keys != expected_keys:
        missing = sorted(expected_keys - supplied_keys)
        undeclared = sorted(supplied_keys - expected_keys)
        raise LineageError(
            f"Freeze-manifest evidence keys differ; missing={missing}, undeclared={undeclared}."
        )
    for key, expected_value in _VERIFIED_FIELDS:
        actual = evidence[key]
        if type(actual) is not type(expected_value) or actual != expected_value:
            raise LineageError(f"Freeze-manifest evidence mismatch for {key}.")

    schema_approval = _approval(schema_approval_id, label="Schema")
    freeze_approval = _approval(freeze_approval_id, label="Freeze")
    if schema_approval.casefold() == freeze_approval.casefold():
        raise LineageError("Schema and freeze approval IDs must be distinct.")

    identity_keys = (
        "market_snapshot_id",
        "market_snapshot_checksum_sha256",
        "source_session_date",
        "content_sha256",
        "ticker_universe_sha256",
        "provider_lineage_sha256",
    )
    identity_sha256 = _canonical_sha256({key: expected[key] for key in identity_keys})
    dataset_version_id = (
        f"oracle-research-{expected['source_session_date'].replace('-', '')}-"
        f"{identity_sha256[:32]}"
    )
    provisional = OracleResearchDatasetFreezeManifest(
        dataset_version_id=dataset_version_id,
        manifest_sha256="",
        schema_approval_id=schema_approval,
        freeze_approval_id=freeze_approval,
        verified_fields=_VERIFIED_FIELDS,
    )
    manifest_sha256 = _canonical_sha256(provisional._payload_without_hash())
    return OracleResearchDatasetFreezeManifest(
        dataset_version_id=dataset_version_id,
        manifest_sha256=manifest_sha256,
        schema_approval_id=schema_approval,
        freeze_approval_id=freeze_approval,
        verified_fields=_VERIFIED_FIELDS,
    )
