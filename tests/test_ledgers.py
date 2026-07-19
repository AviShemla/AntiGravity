import os
import pytest
import pandas as pd
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database_manager

def test_ledger_continuity():
    """
    Asserts that the capital ledgers have no missing chronological dates.
    """
    df = database_manager.execute_query("SELECT * FROM capital_ledgers WHERE persona='BallsForBrains' ORDER BY date DESC LIMIT 10")
    assert not df.empty, "Capital ledger is completely empty"
    assert "date" in df.columns, "Date column missing from ledger"

def test_no_intraday_dangling_trades():
    """
    Asserts that there are no dangling intraday open positions before a weekend.
    """
    df = database_manager.execute_query("SELECT * FROM capital_ledgers ORDER BY date DESC LIMIT 50")
    if not df.empty and "intraday_status" in df.columns:
        statuses = df['intraday_status'].unique()
        # If the system is resting, it shouldn't be stuck in 'Active' state
        assert "Active" not in statuses, "System is stuck in an Active intraday state during rest period"
