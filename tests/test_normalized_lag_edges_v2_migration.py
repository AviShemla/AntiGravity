from pathlib import Path
from scripts.apply_atomic_migration import parse_atomic_bundle

MIGRATION=Path(__file__).resolve().parents[1]/"migrations"/"20260825_normalized_lag_edges_v2.sql"


def sql():
    migration=parse_atomic_bundle(MIGRATION.read_bytes())
    return migration," ".join(" ".join(s.upper().split()) for _,s in migration.statements)


def test_identity_and_additive_contract():
    migration,text=sql()
    assert migration.migration_id=="20260825_normalized_lag_edges_v2"
    assert migration.schema_version==2
    assert len(migration.statements)==19
    for _,statement in migration.statements:
        normalized=" ".join(statement.upper().split())
        assert not normalized.startswith(("DROP ","ALTER ","DELETE ","UPDATE ","INSERT "))


def test_normalized_depth_and_independent_lag_bounds():
    _,text=sql()
    for table in ("PREDICTIVE_SCREENING_EDGE_SETS_V2","PREDICTIVE_SCREENING_EDGES_V2",
                  "STOCK_UNIVERSE_EDGE_SETS_V2","STOCK_UNIVERSE_EDGES_V2"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in text
    assert text.count("EDGE_POSITION INTEGER NOT NULL CHECK (EDGE_POSITION BETWEEN 1 AND 5)")==2
    assert text.count("LAG_SESSIONS INTEGER NOT NULL CHECK (LAG_SESSIONS BETWEEN 1 AND 7)")==2
    assert "LAG1_SESSIONS" not in text and "LAG5_SESSIONS" not in text


def test_dense_depth_and_exact_screening_lineage_guards():
    _,text=sql()
    for required in (
        "SCREENING EDGE COUNT MUST EQUAL DECLARED DEPTH",
        "SCREENING EDGE POSITIONS MUST BE DENSE",
        "UNIVERSE EDGE COUNT MUST EQUAL DECLARED DEPTH",
        "UNIVERSE EDGES MUST EXACTLY EQUAL SCREENING EDGES",
        "REQUIRES MATCHING FROZEN SCREENING EVIDENCE",
        "EXCEPT SELECT EDGE_POSITION, PREDICTOR_TICKER, LAG_SESSIONS, LAG_SEMANTICS",
    ):
        assert required in text


def test_immutable_delete_protected_versioned_evidence():
    _,text=sql()
    for trigger in (
        "TRG_SCHEMA_MIGRATION_EVENTS_V2_NO_UPDATE",
        "TRG_SCHEMA_MIGRATION_EVENTS_V2_NO_DELETE",
        "TRG_PREDICTIVE_SCREENING_EDGES_V2_NO_UPDATE",
        "TRG_PREDICTIVE_SCREENING_EDGES_V2_NO_DELETE",
        "TRG_PREDICTIVE_SCREENING_EDGE_SETS_V2_NO_DELETE",
        "TRG_STOCK_UNIVERSE_EDGES_V2_NO_UPDATE",
        "TRG_STOCK_UNIVERSE_EDGES_V2_NO_DELETE",
        "TRG_STOCK_UNIVERSE_EDGE_SETS_V2_NO_DELETE",
    ):
        assert f"CREATE TRIGGER IF NOT EXISTS {trigger}" in text
    assert text.count("BEFORE DELETE ON")>=4
    assert "PERMITS ONLY DRAFT TO FROZEN" in text


def test_canonical_utc_and_append_only_ledger():
    _,text=sql()
    assert text.count("GLOB '????-??-??T??:??:??Z'")>=7
    assert "LENGTH(EXECUTED_AT_UTC) = 20" in text
    assert "CREATE TABLE IF NOT EXISTS SCHEMA_MIGRATION_EVENTS_V2" in text
    assert "OPERATION TEXT NOT NULL CHECK (OPERATION IN ('APPLY', 'ROLLBACK'))" in text
    assert "UNIQUE (MIGRATION_ID, OPERATION, ARTIFACT_SHA256)" in text
