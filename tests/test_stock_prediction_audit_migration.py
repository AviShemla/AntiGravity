from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260824_stock_prediction_audit_additive.sql"
)


def normalized_sql() -> str:
    text = MIGRATION.read_text(encoding="utf-8")
    uncommented = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("--")
    )
    return " ".join(uncommented.upper().split())


def test_prediction_audit_migration_is_create_only():
    sql = normalized_sql()
    for forbidden in ("DROP ", "DELETE ", "UPDATE ", "ALTER ", "INSERT ", "REPLACE "):
        assert forbidden not in sql
    assert sql.count("CREATE TABLE IF NOT EXISTS") == 2


def test_prediction_audit_schema_preserves_all_three_lanes_and_raw_output():
    sql = normalized_sql()
    for required in (
        "RAW_MODEL_SIGNAL",
        "AG_ACTION",
        "CODEX_ACTION",
        "BALANCED_ACTION",
        "HARD_GATE_FAILURES_JSON",
        "RESOLVED_BASE_PERSONA",
        "STOCK_PREDICTION_CRITERION_AUDITS",
    ):
        assert required in sql


def test_prediction_audit_can_never_authorize_an_order():
    sql = normalized_sql()
    assert "ORDER_AUTHORIZED INTEGER NOT NULL DEFAULT 0 CHECK (ORDER_AUTHORIZED = 0)" in sql
