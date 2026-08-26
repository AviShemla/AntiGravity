import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "governance" / "oracle_research_dataset_application_contract.json"
RUNBOOK_PATH = (
    ROOT / "docs" / "ORACLE_RESEARCH_DATASET_PRODUCTION_APPLICATION_FREEZE_RUNBOOK_20260826.md"
)
CONTENT_EVIDENCE_PATH = (
    ROOT / "docs" / "evidence" / "oracle_research_content_audit_20260826.json"
)
MATRIX_CHECKPOINT_PATH = (
    ROOT / "docs" / "evidence" / "oracle_research_isolated_matrix_checkpoint_20260826.json"
)
MATRIX_READBACK_PATH = (
    ROOT / "docs" / "evidence" / "oracle_research_isolated_matrix_readback_20260826.json"
)
MATRIX_TERMINAL_PATH = (
    ROOT / "docs" / "evidence" / "oracle_research_isolated_matrix_terminal_20260826.json"
)
ORPHAN_PRE_CLEANUP_PATH = (
    ROOT / "docs" / "evidence" / "oracle_research_orphan_branch_pre_cleanup_20260826.json"
)
ORPHAN_FINAL_CLEANUP_PATH = (
    ROOT / "docs" / "evidence" / "oracle_research_orphan_branch_cleanup_final_20260826.json"
)
NORMALIZED_EDGE_EVIDENCE_PATH = (
    ROOT / "docs" / "evidence" / "oracle_normalized_screening_edge_audit_20260826.json"
)
HISTORICAL_QUALITY_EVIDENCE_PATH = (
    ROOT / "docs" / "evidence" / "oracle_pinned_historical_quality_audit_20260826.json"
)


def load_contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_hash_locks_current_reviewed_artifacts():
    contract = load_contract()
    for artifact_name in (
        "schema_migration",
        "read_only_reader",
        "dataset_serializers",
        "dataset_content_reader",
        "freeze_manifest_builder",
        "injected_turso_atomic_adapter",
        "atomic_runner",
    ):
        artifact = contract["artifacts"][artifact_name]
        digest = hashlib.sha256((ROOT / artifact["path"]).read_bytes()).hexdigest()
        assert digest == artifact["sha256"]


def test_runbook_pins_exact_contract_hash():
    digest = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()
    assert digest in RUNBOOK_PATH.read_text(encoding="utf-8")


def test_schema_and_freeze_are_distinct_closed_approval_gates():
    contract = load_contract()
    schema = contract["approval_gates"]["schema_application"]
    freeze = contract["approval_gates"]["dataset_freeze"]
    assert schema["required"] and freeze["required"]
    assert schema["approval_id"] is None and freeze["approval_id"] is None
    assert not schema["authorizes_dataset_freeze"]
    assert not freeze["authorizes_schema_application"]
    assert freeze["must_differ_from"] == "schema_application"
    readiness = contract["execution_readiness"]
    assert not readiness["schema_application_executable"]
    assert not readiness["dataset_freeze_executable"]


def test_schema_artifact_is_atomic_runner_compatible_but_not_approved():
    contract = load_contract()
    artifact = contract["artifacts"]["schema_migration"]
    assert artifact["atomic_runner_compatible"]
    assert artifact["blocker"] is None
    assert artifact["statement_count"] == 26
    assert artifact["migration_id"] == "20260826_oracle_research_dataset_versions_additive"
    blockers = set(contract["execution_readiness"]["schema_blockers"])
    assert blockers == {"SCHEMA_APPROVAL_MISSING"}


def test_isolated_turso_matrix_is_hash_locked_complete_and_cleanup_verified():
    contract = load_contract()
    reference = contract["production_evidence"]["isolated_turso_matrix_readback"]
    assert reference["status"] == "OBSERVED/VERIFIED_READBACK"
    assert reference["artifact_source_git_commit"] == "cf8345c30e2c8264cbb7140bef3b397a7799e488"
    assert reference["executor_git_commit"] == "64e7bc78fd0612591d7dc8ddd6fa8d8dc255d7bf"
    assert reference["migration_sha256"] == contract["artifacts"]["schema_migration"]["sha256"]
    assert reference["statement_count"] == 26
    assert reference["schema_object_count"] == 26
    assert reference["behavioral_assertion_count"] == 26
    assert reference["behavioral_assertions_passed"] == 26
    assert reference["apply_event_count"] == 1
    assert reference["rollback_event_count"] == 1
    assert reference["failed_ddl_probe_rows"] == 0
    assert reference["fixture_event_rows"] == 0
    assert reference["fixture_provider_rows"] == 0
    assert reference["fixture_version_rows"] == 0
    assert reference["production_fingerprint_before"] == reference["production_fingerprint_after"]
    assert reference["production_oracle_object_count_before"] == 0
    assert reference["production_oracle_object_count_after"] == 0
    assert reference["cleanup_verified"] is True
    assert reference["branch_show_readback"] == "EXACT_OBSERVED_NOT_FOUND"
    assert reference["parent_branch_list_readback"] == "EXACT_NAME_ABSENCE"
    assert reference["sanitization"] == {
        "credentials_included": False,
        "database_urls_included": False,
        "response_bodies_included": False,
        "source_rows_included": False,
    }

    for key, path in (
        ("checkpoint", MATRIX_CHECKPOINT_PATH),
        ("matrix_readback", MATRIX_READBACK_PATH),
        ("terminal_cleanup", MATRIX_TERMINAL_PATH),
    ):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == reference[key]["sha256"]

    checkpoint = json.loads(MATRIX_CHECKPOINT_PATH.read_text(encoding="utf-8"))
    readback = json.loads(MATRIX_READBACK_PATH.read_text(encoding="utf-8"))
    terminal = json.loads(MATRIX_TERMINAL_PATH.read_text(encoding="utf-8"))
    claimed_logical_hash = readback.pop("evidence_sha256")
    canonical_readback = json.dumps(
        readback,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    recomputed_logical_hash = hashlib.sha256(canonical_readback).hexdigest()
    assertions = readback["readback"]["assertion_results"]
    assert recomputed_logical_hash == claimed_logical_hash == reference["logical_evidence_sha256"]
    assert checkpoint["state"] == "COMPLETE"
    assert checkpoint["executor_git_commit"] == reference["executor_git_commit"]
    assert len(assertions) == reference["behavioral_assertion_count"]
    assert sum(value is True for value in assertions.values()) == reference["behavioral_assertions_passed"]
    assert readback["redaction"] == {
        "branch_url_included": False,
        "production_url_included": False,
        "response_bodies_included": False,
        "token_included": False,
    }
    assert terminal["cleanup"]["cleanup_verified"] is True
    assert terminal["cleanup"]["production_fingerprint_sha256"] == reference["production_fingerprint_after"]
    assert terminal["matrix_evidence_file_sha256"] == reference["matrix_readback"]["sha256"]


def test_orphan_cleanup_is_separate_hash_locked_and_grants_no_authority():
    contract = load_contract()
    reference = contract["production_evidence"]["orphan_disposable_branch_cleanup"]
    assert reference["status"] == "OBSERVED/VERIFIED_CLEANUP"
    assert reference["branch_name"] == "theoracle-codex-oracle-rd-20260826t1945z-d530dc"
    assert reference["branch_id"] == "01a03f9c-2f01-74bb-8ba2-6b73aaf7b208"
    assert reference["successful_matrix_branch"] is False
    assert reference["matrix_execution_reached"] is False
    matrix = contract["production_evidence"]["isolated_turso_matrix_readback"]
    assert reference["branch_name"] != matrix["disposable_branch_name"]
    assert reference["branch_id"] != matrix["disposable_branch_id"]
    assert reference["production_fingerprint_before"] == reference["production_fingerprint_after"]
    assert reference["production_oracle_object_count_before"] == 0
    assert reference["production_oracle_object_count_after"] == 0
    assert reference["cleanup_verified"] is True
    assert reference["branch_show_readback"] == "EXACT_OBSERVED_NOT_FOUND"
    assert reference["parent_branch_list_readback"] == "EXACT_NAME_ABSENCE"
    assert reference["authorizes_schema_application"] is False
    assert reference["authorizes_dataset_freeze"] is False
    for key, path in (
        ("pre_cleanup", ORPHAN_PRE_CLEANUP_PATH),
        ("final_cleanup", ORPHAN_FINAL_CLEANUP_PATH),
    ):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == reference[key]["sha256"]
    pre = json.loads(ORPHAN_PRE_CLEANUP_PATH.read_text(encoding="utf-8"))
    final = json.loads(ORPHAN_FINAL_CLEANUP_PATH.read_text(encoding="utf-8"))
    assert pre["branch_identity"]["branch_name"] == reference["branch_name"]
    assert pre["branch_identity"]["branch_id"] == reference["branch_id"]
    assert pre["redaction"] == {
        "credentials_included": False,
        "response_bodies_included": False,
        "urls_included": False,
    }
    assert final["pre_cleanup_file_sha256"] == reference["pre_cleanup"]["sha256"]
    assert final["cleanup"]["branch_show_readback"] == "EXACT_OBSERVED_NOT_FOUND"
    assert final["cleanup"]["parent_branch_list_readback"] == "EXACT_NAME_ABSENCE"
    assert final["cleanup"]["production_fingerprint_sha256"] == reference["production_fingerprint_after"]
    assert final["cleanup"]["production_oracle_object_count"] == 0


def test_normalized_edge_audit_is_hash_locked_exact_and_read_only():
    contract = load_contract()
    reference = contract["production_evidence"]["normalized_screening_edge_read_only_audit"]
    assert hashlib.sha256(NORMALIZED_EDGE_EVIDENCE_PATH.read_bytes()).hexdigest() == reference["sha256"]
    evidence = json.loads(NORMALIZED_EDGE_EVIDENCE_PATH.read_text(encoding="utf-8"))
    logical = dict(evidence)
    claimed = logical.pop("evidence_sha256")
    canonical = json.dumps(
        logical,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == claimed == reference["logical_evidence_sha256"]
    assert evidence["coverage"] == {
        "runs_observed": 3,
        "runs_expected": 3,
        "result_rows_observed": 1422,
        "result_rows_expected": 1422,
        "evaluated_rows_inspected": 23,
        "evaluated_rows_expected": 23,
        "extractable_edge_sets": 10,
        "evaluated_without_final_spec": 13,
        "normalized_edges_observed": 19,
        "normalized_edges_expected": 19,
        "eligible_edge_sets": 0,
    }
    assert len(evidence["observational_edge_sets"]) == 10
    assert sum(len(item["edges"]) for item in evidence["observational_edge_sets"]) == 19
    assert all(value == 0 for value in evidence["normalized_table_counts"].values())
    assert all(value == 0 for value in evidence["downstream_counts"].values())
    assert all(
        item == {"object_type": "table", "presence": "PRESENT", "row_count": 0}
        for item in evidence["optional_schema_objects"].values()
    )
    assert reference["optional_schema_state"] == {
        "present_empty_table_count": 7,
        "absent_object_count": 0,
        "nonempty_table_count": 0,
        "present_empty_tables": sorted(evidence["optional_schema_objects"]),
    }
    assert reference["coverage"] == {
        key: evidence["coverage"][key]
        for key in reference["coverage"]
    }
    assert evidence["database_writes"] == evidence["model_fits"] == 0
    assert evidence["etf_prior_outputs"] == 0
    assert reference["authorizes_schema_application"] is False
    assert reference["authorizes_dataset_freeze"] is False
    assert contract["approval_gates"]["schema_application"]["approval_id"] is None
    assert contract["approval_gates"]["dataset_freeze"]["approval_id"] is None


def test_historical_quality_audit_is_hash_locked_exact_and_read_only():
    contract = load_contract()
    reference = contract["production_evidence"]["pinned_historical_quality_read_only_audit"]
    assert reference["status"] == "OBSERVED/VERIFIED_READBACK"
    assert hashlib.sha256(HISTORICAL_QUALITY_EVIDENCE_PATH.read_bytes()).hexdigest() == reference["sha256"]
    evidence = json.loads(HISTORICAL_QUALITY_EVIDENCE_PATH.read_text(encoding="utf-8"))
    logical = dict(evidence)
    claimed = logical.pop("evidence_sha256")
    canonical = json.dumps(
        logical,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == claimed == reference["logical_evidence_sha256"]
    assert evidence["status"] == "PASS"
    assert evidence["read_only"] is True
    assert len(evidence["checks"]) == reference["coverage"]["checks_expected"] == 10
    assert sum(value is True for value in evidence["checks"].values()) == reference["coverage"]["checks_passed"] == 10
    assert reference["coverage"] == {
        "rows_observed": evidence["coverage"]["row_count"],
        "rows_expected": evidence["denominators"]["rows"],
        "tickers_observed": evidence["coverage"]["ticker_count"],
        "tickers_expected": evidence["denominators"]["tickers"],
        "sessions_observed": evidence["coverage"]["session_count"],
        "sessions_expected": evidence["denominators"]["sessions"],
        "ticker_session_cells_observed": evidence["ticker_session_grid"]["observed_cells"],
        "ticker_session_cells_possible": evidence["ticker_session_grid"]["possible_cells"],
        "ticker_session_cells_unavailable": evidence["ticker_session_grid"]["missing_cells"],
        "provider_lineage_rows_observed": evidence["provider_lineage"]["lineage_rows"],
        "provider_lineage_rows_expected": evidence["denominators"]["provider_lineage_rows"],
        "checks_passed": 10,
        "checks_expected": 10,
    }
    assert reference["duplicate_rows"] == evidence["duplicates"]["duplicate_rows"] == 0
    assert reference["duplicate_keys"] == evidence["duplicates"]["duplicate_keys"] == 0
    assert reference["quality_violation_count"] == sum(evidence["quality"].values()) == 0
    assert reference["calendar_missing_sessions"] == evidence["calendar"]["missing_sessions"] == 0
    assert reference["calendar_non_session_dates"] == evidence["calendar"]["non_session_dates"] == 0
    assert reference["provider_lineage_violation_count"] == sum(
        evidence["provider_lineage"][key]
        for key in (
            "feature_tickers_without_lineage",
            "invalid_lineage",
            "invalid_provider",
            "duplicate_lineage",
        )
    ) == 0
    assert reference["fresh_reproduction_select_statements"] == 13
    assert reference["fresh_reproduction_write_statements"] == 0
    assert reference["database_writes"] == 0
    assert reference["authorizes_schema_application"] is False
    assert reference["authorizes_dataset_freeze"] is False
    assert evidence["sanitization"] == {
        "credentials_included": False,
        "source_rows_included": False,
    }
    assert contract["approval_gates"]["schema_application"]["approval_id"] is None
    assert contract["approval_gates"]["dataset_freeze"]["approval_id"] is None


def test_every_database_audit_statement_is_read_only():
    contract = load_contract()
    forbidden = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "REPLACE", "CREATE")
    audit_ids = set()
    for phase, audits in contract["read_only_audits"].items():
        assert audits, phase
        for audit in audits:
            sql = audit["sql"].strip().upper()
            assert sql.startswith("SELECT "), audit["id"]
            assert not any(token in sql.split() for token in forbidden), audit["id"]
            assert audit["id"] not in audit_ids
            audit_ids.add(audit["id"])


def test_rollback_is_evidence_preserving_and_no_drop():
    contract = load_contract()
    boundaries = contract["rollback_boundaries"]
    assert set(boundaries) == {
        "before_schema_begin",
        "before_schema_commit",
        "after_schema_commit_before_freeze",
        "before_freeze_commit",
        "after_freeze_commit",
    }
    post_commit = " ".join(
        (boundaries["after_schema_commit_before_freeze"], boundaries["after_freeze_commit"])
    ).upper()
    assert "NEVER DROP OR DELETE" in post_commit
    assert "NEVER MUTATE, DELETE, OR DROP" in post_commit
    assert {"DROP", "DELETE", "TRUNCATE"}.issubset(
        set(contract["forbidden_rollback_sql"])
    )


def test_duplicate_and_service_safety_gates_are_explicit():
    contract = load_contract()
    duplicate_text = " ".join(contract["duplicate_prevention"])
    assert "schema APPLY ledger" in duplicate_text
    assert "FREEZE event" in duplicate_text
    assert "ambiguous commit" in duplicate_text
    safety = contract["safety_gates"]
    assert safety["operating_mode"] == "FROZEN/RESEARCH"
    assert "ag-sniper.service" in safety["required_inactive_disabled_units"]
    assert "codex-market-ingestion-20260826-v1.service" in safety["required_inactive_units"]
    assert "RECOMMENDATION_OR_ORDER_STAGING" in safety["forbidden_concurrent_actions"]


def test_freeze_is_blocked_after_pure_writer_interface_boundary():
    contract = load_contract()
    writer = contract["artifacts"]["dataset_freeze_writer"]
    assert writer == {
        "status": "IMPLEMENTED/TESTED_INTERFACE",
        "path": "oracle_research_dataset_writer.py",
        "sha256": "0220845dcb870946e38c08055d1ea0a663be8e5cc2232b57b8b237f2eb065adf",
        "production_adapter_status": "IMPLEMENTED_TESTED_BUT_NOT_APPROVED_FOR_EXECUTION",
    }
    assert hashlib.sha256((ROOT / writer["path"]).read_bytes()).hexdigest() == writer["sha256"]
    blockers = set(contract["execution_readiness"]["freeze_blockers"])
    assert "FREEZE_WRITER_NOT_IMPLEMENTED" not in blockers
    assert "PRODUCTION_TRANSACTION_ADAPTER_NOT_IMPLEMENTED_OR_APPROVED" not in blockers
    assert "PRODUCTION_TRANSACTION_ADAPTER_NOT_APPROVED_FOR_EXECUTION" in blockers
    assert "PRODUCTION_SCHEMA_APPLICATION_NOT_APPROVED_OR_APPLIED" in blockers
    assert "CANONICAL_CONTENT_SERIALIZER_NOT_IMPLEMENTED" not in blockers
    assert "CANONICAL_TICKER_UNIVERSE_SERIALIZER_NOT_IMPLEMENTED" not in blockers
    assert "ACTUAL_586710_ROW_DIGEST_READBACK_NOT_PERFORMED" not in blockers
    assert "ACTUAL_DATASET_FREEZE_READBACK_NOT_PERFORMED" in blockers
    assert "SCHEMA_POST_AUDIT_NOT_RECORDED" in blockers
    assert "FREEZE_APPROVAL_MISSING" in blockers


def test_canonical_serializers_are_hash_locked_with_observed_production_readback():
    contract = load_contract()
    assert contract["source_git_commit"] == "eb08ce518a557bf6b772aa66e6bad25e3d681cd3"
    serializers = contract["artifacts"]["dataset_serializers"]
    assert serializers == {
        "status": "IMPLEMENTED/TESTED_INTERFACE",
        "path": "oracle_research_dataset_serializers.py",
        "sha256": "c4b7621663de01dc5a4a56abe73992ae89f9502612e614b7200c13ed3239eac7",
        "content_encoding": "oracle-market-daily-features-jsonl-v1",
        "ticker_universe_encoding": "oracle-market-ticker-universe-jsonl-v1",
    }
    blockers = set(contract["execution_readiness"]["freeze_blockers"])
    assert "ACTUAL_586710_ROW_DIGEST_READBACK_NOT_PERFORMED" not in blockers
    assert "ACTUAL_DATASET_FREEZE_READBACK_NOT_PERFORMED" in blockers


def test_content_reader_is_hash_locked_with_observed_read_only_readback():
    contract = load_contract()
    reader = contract["artifacts"]["dataset_content_reader"]
    assert reader == {
        "status": "IMPLEMENTED/TESTED_READ_ONLY_INTERFACE",
        "path": "oracle_research_dataset_content_reader.py",
        "sha256": "caf92cd75c7399648b9716b7c5ceba30171856ad243d48275fcb1e93e2b1118c",
        "query_mode": "BOUNDED_KEYSET_SELECT_ONLY_STREAMING",
        "retained_row_count": 0,
        "production_digest_readback_status": "OBSERVED/VERIFIED_READBACK",
    }
    assert hashlib.sha256((ROOT / reader["path"]).read_bytes()).hexdigest() == reader["sha256"]
    blockers = set(contract["execution_readiness"]["freeze_blockers"])
    assert "ACTUAL_586710_ROW_DIGEST_READBACK_NOT_PERFORMED" not in blockers
    assert "ACTUAL_DATASET_FREEZE_READBACK_NOT_PERFORMED" in blockers


def test_observed_content_evidence_hash_and_exact_readback_are_reproducible():
    contract = load_contract()
    reference = contract["production_evidence"]["actual_586710_row_digest_readback"]
    assert reference == {
        "status": "OBSERVED/VERIFIED_READBACK",
        "path": "docs/evidence/oracle_research_content_audit_20260826.json",
        "sha256": "a77361be86febdc1ec750a28ba9a989636cb338a1ac52696da4e0ecee426b476",
        "logical_evidence_sha256": "b0b775d6aa4ff37faacb3987a65019724b358cdc86d5aa5967aea927c1401df3",
        "code_git_commit": "2cc365de3e1811c9b870e1e7738d5ec3bcd6d381",
        "read_only": True,
    }
    assert hashlib.sha256(CONTENT_EVIDENCE_PATH.read_bytes()).hexdigest() == reference["sha256"]

    record = json.loads(CONTENT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert record["status"] == "OBSERVED/VERIFIED_READBACK"
    assert record["runtime_evidence"] == {
        "unit": "codex-oracle-content-audit-20260826.service",
        "invocation_id": "9f1c2cd1ed274c66b498550fb89f9314",
        "code_git_commit": "2cc365de3e1811c9b870e1e7738d5ec3bcd6d381",
        "started_at_utc": "2026-08-26T15:03:12Z",
        "terminal_at_utc": "2026-08-26T15:08:28Z",
        "terminal_state": "deactivated successfully",
        "wall_duration_seconds": 316.147,
        "cpu_duration_seconds": 205.17,
        "peak_memory": "84.2M",
        "durable_log_path": "/var/cache/antigravity/oracle-content-audit-20260826.log",
        "durable_log_sha256": "42e1dd787b0e53a167a19a3945a5a593a9657703a5441f5300dac7241e416886",
    }
    logical = record["logical_evidence"]
    claimed_hash = logical.pop("evidence_sha256")
    canonical = json.dumps(
        logical,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    recomputed_hash = hashlib.sha256(canonical).hexdigest()
    assert recomputed_hash == claimed_hash == reference["logical_evidence_sha256"]
    assert record["independent_readback"] == {
        "method": "canonical-json-sha256-with-evidence_sha256-omitted",
        "recomputed_evidence_sha256": recomputed_hash,
        "matches": True,
    }

    content = logical["canonical_content"]
    coverage = logical["coverage"]
    pagination = logical["pagination"]
    assert content["content_sha256"] == "07735e093c39546276082eba82f53a52d43a71cb1cff2d032b58f1315857a834"
    assert content["ticker_universe_sha256"] == "267cdd0dba60a55346ba6f8a6e843259eacae924c9ea8740a093ea2cce3d1e26"
    assert (content["row_count"], content["ticker_count"]) == (586_710, 474)
    assert (coverage["row_count"], coverage["ticker_count"]) == (586_710, 474)
    assert content["first_session_date"] == coverage["first_session_date"] == "2021-09-08"
    assert content["last_session_date"] == coverage["last_session_date"] == "2026-08-25"
    assert pagination == {
        "maximum_page_rows": 4000,
        "nonempty_page_count": 147,
        "page_size": 4000,
        "query_count": 148,
        "retained_row_count": 0,
    }
    assert logical["read_only"] is True
    assert record["sanitization"] == {
        "credentials_included": False,
        "endpoint_included": False,
        "source_rows_included": False,
    }
    assert set(contract["execution_readiness"]["freeze_blockers"]) == {
        "FREEZE_APPROVAL_MISSING",
        "PRODUCTION_TRANSACTION_ADAPTER_NOT_APPROVED_FOR_EXECUTION",
        "PRODUCTION_SCHEMA_APPLICATION_NOT_APPROVED_OR_APPLIED",
        "SCHEMA_POST_AUDIT_NOT_RECORDED",
        "ACTUAL_DATASET_FREEZE_READBACK_NOT_PERFORMED",
    }


def test_manifest_builder_and_injected_adapter_are_hash_locked_but_not_executable():
    contract = load_contract()
    manifest = contract["artifacts"]["freeze_manifest_builder"]
    assert manifest == {
        "status": "IMPLEMENTED/TESTED_REVIEW_ONLY",
        "path": "oracle_research_dataset_freeze_manifest.py",
        "sha256": "6bca13f27fd30e76dd64f393c9647633baceb5e83d592f95e1aa8ed04c46420f",
        "manifest_status": "REVIEW_ONLY",
        "production_manifest_status": "NOT_BUILT",
        "requires_two_distinct_real_approval_ids": True,
    }
    adapter = contract["artifacts"]["injected_turso_atomic_adapter"]
    assert adapter == {
        "status": "IMPLEMENTED/TESTED_INJECTED_INTERFACE",
        "path": "oracle_research_dataset_turso_adapter.py",
        "sha256": "316c13aa221b6c3af3f2b6488f06c82d85b4991d61c4b9b24bc7820e0af504db",
        "execution_status": "NOT_APPROVED_FOR_EXECUTION",
        "production_use_status": "NEVER_USED",
        "owns_endpoint_token_session_or_environment": False,
    }
    for artifact in (manifest, adapter):
        assert hashlib.sha256((ROOT / artifact["path"]).read_bytes()).hexdigest() == artifact["sha256"]
    assert contract["approval_gates"]["schema_application"]["approval_id"] is None
    assert contract["approval_gates"]["dataset_freeze"]["approval_id"] is None
    assert not contract["execution_readiness"]["dataset_freeze_executable"]
