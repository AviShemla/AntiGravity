import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "governance" / "oracle_research_dataset_application_contract.json"
RUNBOOK_PATH = (
    ROOT / "docs" / "ORACLE_RESEARCH_DATASET_PRODUCTION_APPLICATION_FREEZE_RUNBOOK_20260826.md"
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
    assert blockers == {
        "SCHEMA_APPROVAL_MISSING",
        "ISOLATED_TURSO_MATRIX_NOT_RECORDED",
    }


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
        "production_adapter_status": "NOT_IMPLEMENTED_OR_APPROVED",
    }
    assert hashlib.sha256((ROOT / writer["path"]).read_bytes()).hexdigest() == writer["sha256"]
    blockers = set(contract["execution_readiness"]["freeze_blockers"])
    assert "FREEZE_WRITER_NOT_IMPLEMENTED" not in blockers
    assert "PRODUCTION_TRANSACTION_ADAPTER_NOT_IMPLEMENTED_OR_APPROVED" in blockers
    assert "PRODUCTION_SCHEMA_APPLICATION_NOT_APPROVED_OR_APPLIED" in blockers
    assert "CANONICAL_CONTENT_SERIALIZER_NOT_IMPLEMENTED" not in blockers
    assert "CANONICAL_TICKER_UNIVERSE_SERIALIZER_NOT_IMPLEMENTED" not in blockers
    assert "ACTUAL_586710_ROW_DIGEST_READBACK_NOT_PERFORMED" in blockers
    assert "ACTUAL_DATASET_FREEZE_READBACK_NOT_PERFORMED" in blockers
    assert "SCHEMA_POST_AUDIT_NOT_RECORDED" in blockers
    assert "FREEZE_APPROVAL_MISSING" in blockers


def test_canonical_serializers_are_hash_locked_but_have_no_production_readback():
    contract = load_contract()
    assert contract["source_git_commit"] == "499daf4a9a061ae8073a110e5629bdb0463976b5"
    serializers = contract["artifacts"]["dataset_serializers"]
    assert serializers == {
        "status": "IMPLEMENTED/TESTED_INTERFACE",
        "path": "oracle_research_dataset_serializers.py",
        "sha256": "c4b7621663de01dc5a4a56abe73992ae89f9502612e614b7200c13ed3239eac7",
        "content_encoding": "oracle-market-daily-features-jsonl-v1",
        "ticker_universe_encoding": "oracle-market-ticker-universe-jsonl-v1",
    }
    blockers = set(contract["execution_readiness"]["freeze_blockers"])
    assert "ACTUAL_586710_ROW_DIGEST_READBACK_NOT_PERFORMED" in blockers
    assert "ACTUAL_DATASET_FREEZE_READBACK_NOT_PERFORMED" in blockers


def test_content_reader_is_hash_locked_read_only_but_actual_readback_is_unperformed():
    contract = load_contract()
    reader = contract["artifacts"]["dataset_content_reader"]
    assert reader == {
        "status": "IMPLEMENTED/TESTED_READ_ONLY_INTERFACE",
        "path": "oracle_research_dataset_content_reader.py",
        "sha256": "caf92cd75c7399648b9716b7c5ceba30171856ad243d48275fcb1e93e2b1118c",
        "query_mode": "BOUNDED_KEYSET_SELECT_ONLY_STREAMING",
        "retained_row_count": 0,
        "production_digest_readback_status": "NOT_PERFORMED",
    }
    assert hashlib.sha256((ROOT / reader["path"]).read_bytes()).hexdigest() == reader["sha256"]
    blockers = set(contract["execution_readiness"]["freeze_blockers"])
    assert "ACTUAL_586710_ROW_DIGEST_READBACK_NOT_PERFORMED" in blockers
    assert "ACTUAL_DATASET_FREEZE_READBACK_NOT_PERFORMED" in blockers
