from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260824_canonical_market_lineage_additive.sql"
)


def normalized_sql() -> str:
    sql = MIGRATION.read_text(encoding="utf-8")
    uncommented = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )
    return " ".join(uncommented.upper().split())


def test_canonical_market_lineage_migration_is_additive_only():
    sql = normalized_sql()
    for forbidden in ("DROP ", "DELETE ", "UPDATE ", "ALTER ", "INSERT ", "REPLACE "):
        assert forbidden not in sql
    assert sql.count("CREATE TABLE IF NOT EXISTS") == 5


def test_canonical_schema_records_policy_source_and_feature_lineage():
    sql = normalized_sql()
    for table in (
        "MARKET_CANONICAL_POLICIES",
        "MARKET_CANONICAL_BAR_SNAPSHOTS",
        "MARKET_CANONICAL_BARS",
        "MARKET_FEATURE_RECOMPUTE_RUNS",
        "MARKET_FEATURE_RECOMPUTE_KEYS",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    for required in (
        "PROVIDER_PRIORITY_JSON",
        "EVIDENCE_CUTOFF_UTC",
        "SOURCE_VALUE_SHA256",
        "CANONICAL_PROVIDER",
        "CANONICAL_RUN_ID",
        "PARENT_MARKET_SNAPSHOT_ID",
        "OUTPUT_MARKET_SNAPSHOT_ID",
        "PATCH_CONTENT_SHA256",
        "RECOMPUTE_SCOPE",
    ):
        assert required in sql


def test_only_one_canonical_policy_can_be_approved():
    sql = normalized_sql()
    assert "CREATE UNIQUE INDEX IF NOT EXISTS IDX_MARKET_CANONICAL_POLICY_APPROVED" in sql
    assert "WHERE STATUS = 'APPROVED'" in sql


def test_recompute_lineage_cannot_claim_zero_planned_keys():
    sql = normalized_sql()
    assert "PLANNED_KEY_COUNT INTEGER NOT NULL CHECK (PLANNED_KEY_COUNT > 0)" in sql


def test_snapshot_and_recompute_statuses_are_explicit():
    sql = normalized_sql()
    assert "STATUS IN ('STAGING', 'VALIDATED', 'FAILED')" in sql
    assert "STATUS IN ('PLANNED', 'STAGING', 'VALIDATED', 'FAILED')" in sql
