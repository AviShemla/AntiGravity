from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
import hashlib

import pytest

try:
    from .frozen_dataset_input_gap import (
        EXPECTED_PAYLOADS,
        FREEZE_READBACK_FIELDS,
        FreezeReadbackGapError,
        audit_freeze_readback_gap,
        canonical_bytes,
        require_normalized_edge_inputs,
    )
except ImportError:
    from frozen_dataset_input_gap import (
        EXPECTED_PAYLOADS,
        FREEZE_READBACK_FIELDS,
        FreezeReadbackGapError,
        audit_freeze_readback_gap,
        canonical_bytes,
        require_normalized_edge_inputs,
    )


@dataclass(frozen=True)
class OracleResearchDatasetVersionFixture:
    dataset_version_id: str
    market_snapshot_id: str
    market_snapshot_checksum_sha256: str
    source_session_date: date
    evidence_cutoff_utc: datetime
    first_session_date: date
    last_session_date: date
    expected_row_count: int
    expected_ticker_count: int
    expected_session_count: int
    expected_provider_lineage_count: int
    content_sha256: str
    ticker_universe_sha256: str
    provider_lineage_sha256: str
    schema_version: str
    code_version: str
    freeze_approval_id: str
    frozen_by: str
    frozen_at_utc: datetime
    provider_lineage: tuple[object, ...]


def freeze_fixture() -> OracleResearchDatasetVersionFixture:
    return OracleResearchDatasetVersionFixture(
        dataset_version_id="oracle-research-20260825-843955ade32387172c33e5c3eec167dc",
        market_snapshot_id="market_features_2026-08-25_5b1044ee45605a3d",
        market_snapshot_checksum_sha256="a" * 64,
        source_session_date=date(2026, 8, 25),
        evidence_cutoff_utc=datetime(2026, 8, 26, 7, tzinfo=timezone.utc),
        first_session_date=date(2021, 9, 8),
        last_session_date=date(2026, 8, 25),
        expected_row_count=586_710,
        expected_ticker_count=474,
        expected_session_count=1_244,
        expected_provider_lineage_count=476,
        content_sha256="b" * 64,
        ticker_universe_sha256="c" * 64,
        provider_lineage_sha256="d" * 64,
        schema_version="oracle-research-dataset-v1",
        code_version="8" * 40,
        freeze_approval_id="avi-freeze-oracle-rd-20260827-d0ae4b277bd6",
        frozen_by="Avi Shemla",
        frozen_at_utc=datetime(2026, 8, 27, 13, 30, tzinfo=timezone.utc),
        provider_lineage=(),
    )


def test_exact_frozen_readback_shape_is_evidence_only_and_fails_closed():
    frozen = freeze_fixture()
    with pytest.raises(FreezeReadbackGapError) as captured:
        require_normalized_edge_inputs(frozen)
    report = captured.value.report
    assert report.sufficient is False
    assert report.observed_freeze_fields == FREEZE_READBACK_FIELDS
    assert (report.expected_targets, report.expected_folds, report.expected_payloads) == (
        474, 4, EXPECTED_PAYLOADS,
    )
    assert tuple(item["input_id"] for item in report.missing_inputs) == (
        "model_session_calendar",
        "market_feature_rows",
        "fold_local_normalized_edge_selections",
        "s07_preregistration_proof",
        "fold_payload_lineage",
    )


def test_report_is_deterministic_hash_only_evidence():
    first = audit_freeze_readback_gap(freeze_fixture())
    second = audit_freeze_readback_gap(freeze_fixture())
    assert first == second
    payload = {key: value for key, value in first.__dict__.items() if key != "evidence_sha256"}
    assert first.evidence_sha256 == hashlib.sha256(canonical_bytes(payload)).hexdigest()
    raw = canonical_bytes(first)
    assert b"market_feature_rows" in raw
    assert b"database_writes\":0" in raw
    assert b"token" not in raw.lower() and b"credential" not in raw.lower()


def test_metadata_changes_do_not_manufacture_missing_rows_or_edges():
    frozen = freeze_fixture()
    changed = replace(frozen, expected_row_count=frozen.expected_row_count + 1)
    assert audit_freeze_readback_gap(changed).missing_inputs == audit_freeze_readback_gap(frozen).missing_inputs
    with pytest.raises(FreezeReadbackGapError):
        require_normalized_edge_inputs(changed)


def test_unknown_freeze_shape_is_rejected_before_claiming_gap_evidence():
    @dataclass(frozen=True)
    class Drifted:
        dataset_version_id: str

    with pytest.raises(TypeError, match="field contract differs"):
        audit_freeze_readback_gap(Drifted("dataset"))
    with pytest.raises(TypeError, match="dataclass"):
        audit_freeze_readback_gap({"dataset_version_id": "dataset"})


def test_module_surface_has_no_io_or_execution_capability():
    try:
        from . import frozen_dataset_input_gap as module
    except ImportError:
        import frozen_dataset_input_gap as module

    names = set(vars(module))
    assert names.isdisjoint({"sqlite3", "requests", "urllib", "subprocess", "socket"})
    assert audit_freeze_readback_gap(freeze_fixture()).side_effects == {
        "database_reads": 0,
        "database_writes": 0,
        "network_calls": 0,
        "model_fits": 0,
        "predictions": 0,
        "recommendations": 0,
        "orders": 0,
        "etf_outputs": 0,
    }
