import pytest
import httpx
import datetime

API_BASE = "http://66.42.118.26:80/api"

def test_regression_3am_hardcode_bug():
    """
    REGRESSION: The server previously hardcoded the next Olympic run to 3:00 AM daily (and originally Saturday 14:00).
    This test hits the live API and mathematically guarantees that the returned eta_timestamp
    strictly targets exactly 01:00:00 (1:00 AM) local time, preventing this bug from recurring.
    """
    response = httpx.get(f"{API_BASE}/olympic")
    assert response.status_code == 200, "API returned non-200 status code"
    
    data = response.json()
    assert "eta_timestamp" in data, "eta_timestamp key missing from response"
    
    # Parse the returned ISO timestamp
    try:
        target_date = datetime.datetime.fromisoformat(data["eta_timestamp"])
    except ValueError:
        pytest.fail(f"eta_timestamp '{data['eta_timestamp']}' is not a valid ISO format")
        
    # The crucial assertion: Ensure the hour is strictly 1 (1:00 AM) and minutes/seconds are 0
    assert target_date.hour == 1, f"Regression Caught! Timer is targeting hour {target_date.hour} instead of 1 AM."
    assert target_date.minute == 0, f"Timer minute is not 0: {target_date.minute}"
    assert target_date.second == 0, f"Timer second is not 0: {target_date.second}"

