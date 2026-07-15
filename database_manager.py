import os
import json
import pandas as pd
from dotenv import load_dotenv
import libsql_client

load_dotenv()

TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

_global_client = None

def get_connection():
    """Returns a connected libsql_client sync client from a global pool."""
    global _global_client
    if _global_client is None:
        if not TURSO_URL or not TURSO_TOKEN:
            raise ValueError("Missing TURSO credentials in .env file!")
        _global_client = libsql_client.create_client_sync(url=TURSO_URL, auth_token=TURSO_TOKEN)
    return _global_client

import atexit
@atexit.register
def close_global_client():
    global _global_client
    if _global_client is not None:
        try:
            _global_client.close()
        except:
            pass

def execute_query(query, args=None):
    """Generic helper to execute SELECT queries and return a DataFrame."""
    client = get_connection()
    res = client.execute(query, args or [])
    if not res.rows:
        return pd.DataFrame(columns=res.columns)
    return pd.DataFrame([list(row) for row in res.rows], columns=res.columns)

def init_db():
    """Initializes the database schema if it doesn't exist."""
    client = get_connection()
    try:
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
    finally:
        pass

def _enforce_double_entry_accounting(cash, total_equity, holdings_json):
    """
    Strict banking failsafe. Total Equity MUST EXACTLY EQUAL Cash + Active Holdings.
    If it doesn't, we override the Cash value.
    """
    try:
        import json
        holdings = json.loads(holdings_json) if isinstance(holdings_json, str) else holdings_json
        if not holdings: holdings = {}
        
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
    try:
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
        ''', [persona, date, float(cash), float(total_equity), json.dumps(holdings_json) if isinstance(holdings_json, dict) else holdings_json, 
              json.dumps(daily_pnl_json) if isinstance(daily_pnl_json, dict) else daily_pnl_json, intraday_status, engine_version])
    finally:
        pass

def get_ledger(persona):
    client = get_connection()
    try:
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
        df = pd.DataFrame([list(row) for row in res.rows], columns=res.columns)
        return df
    finally:
        pass

def save_pending_order(persona, date, target_cash, target_equity, target_holdings, daily_pnl, executed_trades):
    target_cash = _enforce_double_entry_accounting(target_cash, target_equity, target_holdings)
    client = get_connection()
    try:
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
    finally:
        pass

def get_pending_order(persona):
    client = get_connection()
    try:
        res = client.execute("SELECT * FROM pending_orders WHERE persona = ?", [persona])
        if res.rows:
            return dict(zip(res.columns, res.rows[0]))
        return None
    finally:
        pass

def update_continuity(pipeline_name, date_str):
    client = get_connection()
    try:
        client.execute('''
            INSERT INTO process_continuity (pipeline_name, last_completed_date)
            VALUES (?, ?)
            ON CONFLICT(pipeline_name) DO UPDATE SET
                last_completed_date=excluded.last_completed_date
        ''', [pipeline_name, date_str])
    finally:
        pass

def get_last_continuity_date(pipeline_name):
    client = get_connection()
    try:
        res = client.execute("SELECT last_completed_date FROM process_continuity WHERE pipeline_name = ?", [pipeline_name])
        if res.rows:
            return res.rows[0][0]
        return None
    finally:
        pass

if __name__ == "__main__":
    init_db()
    print("Turso Database Schema Initialized.")
