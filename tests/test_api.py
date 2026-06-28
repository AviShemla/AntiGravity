import pytest
import httpx

API_BASE = "http://localhost:80/api"

def test_neutral_holdings_api():
    """
    Asserts that the Neutral persona returns valid data from the /holdings endpoint.
    This prevents 'Ledger not found or empty' UI errors on the dashboard.
    """
    response = httpx.get(f"{API_BASE}/holdings?persona=Neutral&mode=Single")
    assert response.status_code == 200, "API returned non-200 status code"
    
    data = response.json()
    assert "total_equity" in data, "total_equity key missing from response"
    assert "total_return" in data, "total_return key missing from response"
    assert "allocations" in data, "allocations key missing from response"
    assert "equity_curve" in data, "equity_curve key missing from response"

def test_olympic_api():
    """
    Asserts that the Olympic endpoint returns valid marathon backtest data.
    """
    response = httpx.get(f"{API_BASE}/olympic")
    assert response.status_code == 200, "Olympic API returned non-200 status code"
    
    data = response.json()
    assert "chart_data" in data, "chart_data missing from Olympic response"
