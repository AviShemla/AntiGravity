from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260824_independent_lag_sessions_additive.sql"
)


def test_independent_lag_migration_is_additive_and_complete():
    sql = MIGRATION.read_text(encoding="utf-8")
    uncommented = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )
    normalized = " ".join(uncommented.upper().split())
    expected = {
        f"ALTER TABLE {table.upper()} ADD COLUMN LAG{position}_SESSIONS INTEGER;"
        for table in ("predictive_screening_results", "stock_universe_config")
        for position in range(1, 6)
    }
    statements = {
        " ".join(statement.split()) + ";"
        for statement in normalized.split(";")
        if statement.strip().startswith("ALTER TABLE")
    }
    assert statements == expected
    for forbidden in ("DROP ", "DELETE ", "UPDATE ", "INSERT ", "CREATE TABLE"):
        assert forbidden not in normalized
