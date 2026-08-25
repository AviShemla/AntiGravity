import warnings
import asyncio
warnings.filterwarnings("ignore", message="Unclosed client session")
warnings.filterwarnings("ignore", message="Unclosed connector")
import os
import json
import pandas as pd
from dotenv import load_dotenv
import libsql_client
import threading

from model_lineage import LineageError
from turso_read_pipeline import TursoReadPipeline

load_dotenv()

TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

# Singleton connection pool — one reusable client per thread.
# NEVER call client.close() — that destroys the singleton and causes CLIENT_CLOSED errors.
# This is the structural fix for the 'Too many open files' exhaustion bug.
_local = threading.local()

def get_connection():
    """Returns a reusable singleton libsql_client per thread."""
    if not TURSO_URL or not TURSO_TOKEN:
        raise ValueError("Missing TURSO credentials in .env file!")
    if not getattr(_local, 'client', None):
        _local.client = libsql_client.create_client_sync(url=TURSO_URL, auth_token=TURSO_TOKEN)
    return _local.client

def _https_pipeline_endpoint(raw_url):
    """Normalize the configured Turso URL to the canonical HTTPS pipeline."""
    value = str(raw_url or "").strip()
    if value.startswith("libsql://"):
        value = "https://" + value[len("libsql://"):]
    if not value.startswith("https://"):
        raise LineageError("Turso read URL must use libsql:// or https://.")
    value = value.rstrip("/")
    if not value.endswith("/v2/pipeline"):
        value += "/v2/pipeline"
    return value


def get_read_connection():
    """Return one bounded, read-only HTTPS Turso adapter per thread."""
    if not TURSO_URL or not TURSO_TOKEN:
        raise ValueError("Missing TURSO credentials in environment.")
    endpoint = _https_pipeline_endpoint(TURSO_URL)
    client = getattr(_local, "read_client", None)
    if client is None or getattr(_local, "read_endpoint", None) != endpoint:
        client = TursoReadPipeline(endpoint, TURSO_TOKEN)
        _local.read_client = client
        _local.read_endpoint = endpoint
    return client


def execute_query(query, args=None):
    """Execute a bounded SELECT through Turso's canonical HTTPS pipeline."""
    client = get_read_connection()
    res = client.execute(query, args or [])
    if not res.rows:
        return pd.DataFrame(columns=res.columns)
    return pd.DataFrame([list(row) for row in res.rows], columns=res.columns)

def execute_write(query, args=None):
    """Generic helper to execute INSERT/UPDATE/DELETE statements safely."""
    client = get_connection()
    stmt = libsql_client.Statement(query, args or [])
    client.batch([stmt])


def close_connection_for_cli_exit():
    """Close this thread's client when a short-lived CLI audit is finished.

    Long-running services must not call this between requests; it exists only
    so standalone evidence scripts do not leave a libsql worker thread alive.
    """
    client = getattr(_local, 'client', None)
    if client is not None:
        client.close()
        _local.client = None
    _local.read_client = None
    _local.read_endpoint = None


def init_db():
    """Initializes the database schema if it doesn't exist."""
    client = get_connection()

    # 1. Capital Ledgers Table
    client.execute('''
        CREATE TABLE IF NOT EXISTS capital_ledgers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            persona TEXT NOT NULL,
            date TEXT NOT NULL,
            cash REAL NOT NULL,
            total_equity REAL NOT NULL,
            holdings_json TEXT NOT NULL,
            daily_pnl_json TEXT NOT NULL,
            intraday_status TEXT,
            engine_version TEXT DEFAULT 'V1.0 - Pure PyMC Bayesian',
            UNIQUE(persona, date)
        )
    ''')

    # Retroactive DB Upgrade (Will fail silently if column already exists)
    try:
        client.execute("ALTER TABLE capital_ledgers ADD COLUMN engine_version TEXT DEFAULT 'V1.0 - Pure PyMC Bayesian'")
    except Exception:
        pass

    # 2. Pending Orders / Target Allocations Table
    client.execute('''
        CREATE TABLE IF NOT EXISTS pending_orders (
            persona TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            target_cash REAL NOT NULL,
            target_total_equity REAL NOT NULL,
            target_holdings_json TEXT NOT NULL,
            daily_pnl_json TEXT NOT NULL,
            executed_intraday_trades_json TEXT NOT NULL
        )
    ''')

    # 3. Executed Trades Table
    client.execute('''
        CREATE TABLE IF NOT EXISTS executed_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            persona TEXT NOT NULL,
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            action TEXT NOT NULL,
            units REAL NOT NULL,
            price REAL NOT NULL,
            total_value REAL NOT NULL,
            pnl REAL
        )
    ''')

    # 4. Continuity / Catch-Up Ledger
    client.execute('''
        CREATE TABLE IF NOT EXISTS process_continuity (
            pipeline_name TEXT PRIMARY KEY,
            last_completed_date TEXT NOT NULL
        )
    ''')

    # 5. Olympic Shootout Master Table (Normalized Long Schema)
    client.execute('''
        CREATE TABLE IF NOT EXISTS olympic_shootout_master (
            date TEXT NOT NULL,
            model_name TEXT NOT NULL,
            total_equity REAL NOT NULL,
            PRIMARY KEY (date, model_name)
        )
    ''')

    # 6. Prod vs Shadow Master Table (Normalized Long Schema)
    client.execute('''
        CREATE TABLE IF NOT EXISTS prod_vs_shadow_master (
            date TEXT NOT NULL,
            model_name TEXT NOT NULL,
            total_equity REAL NOT NULL,
            PRIMARY KEY (date, model_name)
        )
    ''')

    # 7. ETF & Stock Scorecards Master Table
    client.execute('''
        CREATE TABLE IF NOT EXISTS etf_scorecards_master (
            ticker TEXT NOT NULL,
            persona TEXT NOT NULL,
            date TEXT NOT NULL,
            score REAL,
            prob REAL,
            PRIMARY KEY (ticker, persona, date)
        )
    ''')


def _enforce_double_entry_accounting(cash, total_equity, holdings_json):
    """
    Strict banking failsafe. Total Equity MUST EXACTLY EQUAL Cash + Active Holdings.
    If it doesn't, we override the Cash value.
    """
    try:
        holdings = json.loads(holdings_json) if isinstance(holdings_json, str) else holdings_json
        if not holdings:
            holdings = {}
        true_holdings_value = sum(float(h.get('dollars', 0.0)) for h in holdings.values())
        calculated_equity = float(cash) + true_holdings_value
        if abs(calculated_equity - float(total_equity)) > 0.1:
            correct_cash = float(total_equity) - true_holdings_value
            print(f"  [ACCOUNTING INTERCEPT] Bad math detected! Passed Cash: ${float(cash):.2f}, Equity: ${float(total_equity):.2f}, Holdings: ${true_holdings_value:.2f}")
            print(f"  [ACCOUNTING INTERCEPT] Forcefully correcting Cash to: ${correct_cash:.2f}")
            return correct_cash
        return float(cash)
    except Exception as e:
        print(f"  [ACCOUNTING INTERCEPT ERROR] {e}. Trusting passed cash.")
        return float(cash)


def save_ledger_row(persona, date, cash, total_equity, holdings_json, daily_pnl_json, intraday_status="", engine_version="V1.0 - Pure PyMC Bayesian"):
    cash = _enforce_double_entry_accounting(cash, total_equity, holdings_json)
    client = get_connection()
    client.execute('''
        INSERT INTO capital_ledgers (persona, date, cash, total_equity, holdings_json, daily_pnl_json, intraday_status, engine_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(persona, date) DO UPDATE SET
            cash=excluded.cash,
            total_equity=excluded.total_equity,
            holdings_json=excluded.holdings_json,
            daily_pnl_json=excluded.daily_pnl_json,
            intraday_status=excluded.intraday_status,
            engine_version=excluded.engine_version
    ''', [persona, date, float(cash), float(total_equity),
          json.dumps(holdings_json) if isinstance(holdings_json, dict) else holdings_json,
          json.dumps(daily_pnl_json) if isinstance(daily_pnl_json, dict) else daily_pnl_json,
          intraday_status, engine_version])


def get_ledger(persona):
    client = get_connection()
    query = f"""
        SELECT date as Date, cash as Cash, total_equity as Total_Equity,
               holdings_json as Holdings_JSON, daily_pnl_json as Daily_PnL_JSON,
               intraday_status as Intraday_Status, engine_version as Engine_Version
        FROM capital_ledgers
        WHERE persona = '{persona}' ORDER BY date ASC
    """
    res = client.execute(query)
    if not res.rows:
        return pd.DataFrame(columns=res.columns)
    return pd.DataFrame([list(row) for row in res.rows], columns=res.columns)


def save_pending_order(persona, date, target_cash, target_equity, target_holdings, daily_pnl, executed_trades):
    target_cash = _enforce_double_entry_accounting(target_cash, target_equity, target_holdings)
    client = get_connection()
    client.execute('''
        INSERT INTO pending_orders (persona, date, target_cash, target_total_equity, target_holdings_json, daily_pnl_json, executed_intraday_trades_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(persona) DO UPDATE SET
            date=excluded.date,
            target_cash=excluded.target_cash,
            target_total_equity=excluded.target_total_equity,
            target_holdings_json=excluded.target_holdings_json,
            daily_pnl_json=excluded.daily_pnl_json,
            executed_intraday_trades_json=excluded.executed_intraday_trades_json
    ''', [persona, date, float(target_cash), float(target_equity),
          json.dumps(target_holdings) if isinstance(target_holdings, dict) else target_holdings,
          json.dumps(daily_pnl) if isinstance(daily_pnl, dict) else daily_pnl,
          json.dumps(executed_trades) if isinstance(executed_trades, dict) else executed_trades])


def get_pending_order(persona):
    client = get_connection()
    res = client.execute("SELECT * FROM pending_orders WHERE persona = ?", [persona])
    if res.rows:
        return dict(zip(res.columns, res.rows[0]))
    return None


def get_approved_pending_order(persona):
    """Return legacy pending data only when an unconsumed approved plan proves it.

    Missing execution-lineage tables are an expected fail-closed state during
    migration.  Callers receive an evidence status and must not show the legacy
    pending row as executable.
    """
    from dashboard_data_contract import approved_pending_row

    pending = get_pending_order(persona)
    if pending is None:
        return None, "NO_PENDING_ROW"
    try:
        plans = execute_query(
            """
            SELECT ep.plan_id,ep.persona,ep.target_date,ep.pending_payload_sha256,
                   ep.qa_status,epa.decision AS approval_decision,
                   epc.plan_id AS consumed_plan_id
            FROM execution_plans ep
            LEFT JOIN execution_plan_approvals epa ON epa.plan_id=ep.plan_id
            LEFT JOIN execution_plan_consumptions epc ON epc.plan_id=ep.plan_id
            WHERE ep.persona=? AND ep.target_date=?
            ORDER BY ep.created_at_utc DESC LIMIT 1
            """,
            [persona, str(pending["date"])[:10]],
        )
    except Exception:
        return None, "EXECUTION_LINEAGE_UNAVAILABLE"
    plan = None if plans.empty else plans.iloc[0].to_dict()
    return approved_pending_row(pending, plan)


def get_validated_benchmark_rows(ticker, start_date, end_date):
    """Read benchmark closes from the latest validated DB snapshot only."""
    snapshot = execute_query(
        """
        SELECT snapshot_id,source_session_date,available_at_utc
        FROM model_input_snapshots
        WHERE dataset_type='MARKET_FEATURES' AND status='VALIDATED'
        ORDER BY source_session_date DESC,available_at_utc DESC LIMIT 1
        """
    )
    if snapshot.empty:
        return [], {"status": "NO_VALIDATED_MARKET_SNAPSHOT"}
    row = snapshot.iloc[0]
    prices = execute_query(
        """
        SELECT date,close_price FROM market_daily_features
        WHERE snapshot_id=? AND ticker=? AND date>=? AND date<=?
        ORDER BY date ASC
        """,
        [str(row["snapshot_id"]), ticker, start_date, end_date],
    )
    return prices.to_dict("records"), {
        "status": "VALIDATED",
        "snapshot_id": str(row["snapshot_id"]),
        "source_session_date": str(row["source_session_date"]),
    }


def update_continuity(pipeline_name, date_str):
    client = get_connection()
    client.execute('''
        INSERT INTO process_continuity (pipeline_name, last_completed_date)
        VALUES (?, ?)
        ON CONFLICT(pipeline_name) DO UPDATE SET
            last_completed_date=excluded.last_completed_date
    ''', [pipeline_name, date_str])


def get_last_continuity_date(pipeline_name):
    try:
        client = get_connection()
        res = client.execute("SELECT last_completed_date FROM process_continuity WHERE pipeline_name = ?", [pipeline_name])
        if res.rows and res.rows[0][0]:
            return res.rows[0][0]
    except Exception:
        pass
    # Fallback to actual latest date in capital_ledgers so we never falsely trigger multi-day catchups
    try:
        client = get_connection()
        res_df = execute_query("SELECT MAX(date) FROM capital_ledgers")
        if not res_df.empty and res_df.iloc[0][0]:
            return str(res_df.iloc[0][0])
    except Exception:
        pass
    return None


if __name__ == "__main__":
    init_db()
    print("Turso Database Schema Initialized.")
