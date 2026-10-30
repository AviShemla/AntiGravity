from datetime import datetime, timezone
import pytest
from scripts.apply_atomic_migration import (
    AtomicMigrationError, apply_atomic_migration, build_atomic_statement_batch,
    canonical_utc_seconds, parse_atomic_bundle, resolve_target_environment,
    verify_expected_hash, verify_pipeline_results,
)


def bundle():
    return (
        b"-- migration-id: 20260825_test_bundle\n-- schema-version: 2\n"
        b"-- statement: one\nCREATE TABLE IF NOT EXISTS x (id TEXT PRIMARY KEY)\n"
        b"-- end-statement\n-- statement: guard\n"
        b"CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON x\n"
        b"BEGIN\nSELECT RAISE(ABORT, 'no');\nEND\n-- end-statement\n"
    )


class FakeResponse:
    def __init__(self,payload,status_code=200):
        self.payload=payload; self.status_code=status_code
    def json(self): return self.payload


class FakeSession:
    def __init__(self,payloads): self.payloads=list(payloads); self.calls=[]
    def post(self,url,**kwargs):
        self.calls.append((url,kwargs))
        return FakeResponse(self.payloads.pop(0))


def ok(baton): return {"baton":baton,"results":[{"type":"ok"}]}


def test_parser_preserves_trigger_semicolons():
    migration=parse_atomic_bundle(bundle())
    assert migration.migration_id=="20260825_test_bundle"
    assert migration.schema_version==2
    assert len(migration.statements)==2
    assert "RAISE(ABORT, 'no');" in migration.statements[1][1]


def test_parser_rejects_unmarked_and_nonadditive_sql():
    with pytest.raises(ValueError,match="statement markers"):
        parse_atomic_bundle(b"-- migration-id: 20260825_bad_bundle\n-- schema-version: 2\nDROP TABLE x;\n")
    with pytest.raises(ValueError,match="non-additive"):
        parse_atomic_bundle(
            b"-- migration-id: 20260825_bad_bundle\n-- schema-version: 2\n"
            b"-- statement: bad\nALTER TABLE x ADD COLUMN y TEXT\n-- end-statement\n"
        )


def test_hash_pin_is_exact():
    migration=parse_atomic_bundle(bundle())
    verify_expected_hash(migration,migration.artifact_sha256)
    with pytest.raises(ValueError,match="does not match"):
        verify_expected_hash(migration,"0"*64)
    with pytest.raises(ValueError,match="64 lowercase"):
        verify_expected_hash(migration,"ABC")


def test_timestamp_is_canonical_seconds():
    value=canonical_utc_seconds(datetime(2026,8,25,8,9,10,123456,tzinfo=timezone.utc))
    assert value=="2026-08-25T08:09:10Z"
    with pytest.raises(ValueError,match="timezone-aware"):
        canonical_utc_seconds(datetime(2026,8,25,8,9,10))


def test_statement_batch_contains_migration_and_ledger_without_commit():
    migration=parse_atomic_bundle(bundle())
    requests=build_atomic_statement_batch(migration,event_id="event-1",actor="test",
        target_database_id="isolated",evidence={"scope":"test"},
        executed_at_utc="2026-08-25T08:09:10Z")
    assert [r["stmt"]["sql"] for r in requests[:2]]==[sql for _,sql in migration.statements]
    assert "INSERT INTO schema_migration_events_v2" in requests[-1]["stmt"]["sql"]
    assert len(requests[-1]["stmt"]["args"])==9
    assert all(r["stmt"]["sql"] not in ("BEGIN IMMEDIATE","COMMIT") for r in requests)


def test_batch_rejects_noncanonical_timestamp():
    with pytest.raises(ValueError,match="canonical UTC"):
        build_atomic_statement_batch(parse_atomic_bundle(bundle()),event_id="e",actor="a",
            target_database_id="isolated",evidence={},
            executed_at_utc="2026-08-25T08:09:10+00:00")


def test_result_verification_fails_closed():
    verify_pipeline_results({"results":[{"type":"ok"}]*5},5)
    with pytest.raises(AtomicMigrationError,match="incomplete"):
        verify_pipeline_results({"results":[{"type":"ok"}]},2)
    with pytest.raises(AtomicMigrationError,match="result indexes"):
        verify_pipeline_results({"results":[{"type":"ok"},{"type":"error"}]},2)


def test_success_uses_baton_and_accepts_terminal_commit_without_baton():
    migration=parse_atomic_bundle(bundle())
    step_count=len(migration.statements)+1
    session=FakeSession([
        ok("b1"),
        {"baton":"b2","results":[{"type":"ok"}]*step_count},
        ok(None),
    ])
    apply_atomic_migration(session,"https://isolated/v2/pipeline","token",migration,
        event_id="event-1",actor="test",target_database_id="isolated",evidence={},
        executed_at_utc="2026-08-25T08:09:10Z")
    bodies=[call[1]["json"] for call in session.calls]
    assert bodies[0]["requests"][0]["stmt"]["sql"]=="BEGIN IMMEDIATE"
    assert bodies[1]["baton"]=="b1"
    assert all(r["stmt"]["sql"]!="COMMIT" for r in bodies[1]["requests"])
    assert bodies[2]["baton"]=="b2"
    assert bodies[2]["requests"][0]["stmt"]["sql"]=="COMMIT"
    assert len(bodies)==3


def test_failure_rolls_back_and_never_commits():
    migration=parse_atomic_bundle(bundle())
    step_count=len(migration.statements)+1
    failed=[{"type":"ok"},{"type":"error"}]+[{"type":"ok"}]*(step_count-2)
    session=FakeSession([
        ok("b1"),
        {"baton":"b2","results":failed},
        ok(None),
    ])
    with pytest.raises(AtomicMigrationError,match="result indexes"):
        apply_atomic_migration(session,"https://isolated/v2/pipeline","token",migration,
            event_id="event-1",actor="test",target_database_id="isolated",evidence={},
            executed_at_utc="2026-08-25T08:09:10Z")
    sqls=[req["stmt"].get("sql") for _,call in session.calls
          for req in call["json"]["requests"] if req["type"]=="execute"]
    assert "ROLLBACK" in sqls
    assert "COMMIT" not in sqls


def test_isolated_target_cannot_alias_production(monkeypatch):
    monkeypatch.setenv("TURSO_ISOLATED_DATABASE_URL","libsql://isolated.example")
    monkeypatch.setenv("TURSO_ISOLATED_AUTH_TOKEN","test-only")
    monkeypatch.setenv("TURSO_DATABASE_URL","libsql://production.example")
    endpoint,token=resolve_target_environment("isolated",None)
    assert endpoint=="https://isolated.example/v2/pipeline"
    assert token=="test-only"
    monkeypatch.setenv("TURSO_ISOLATED_DATABASE_URL","libsql://production.example")
    with pytest.raises(ValueError,match="resolves to production"):
        resolve_target_environment("isolated",None)


def test_production_target_requires_recorded_approval(monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL","libsql://production.example")
    monkeypatch.setenv("TURSO_AUTH_TOKEN","test-only")
    with pytest.raises(ValueError,match="approval id"):
        resolve_target_environment("production",None)
    endpoint,_=resolve_target_environment("production","approval-123")
    assert endpoint=="https://production.example/v2/pipeline"
