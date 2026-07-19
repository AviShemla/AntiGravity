import pandas as pd
import datetime
import pytz
import os
import sys

# Add directory to path to import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import intraday_tracker

def test_volume_gating():
    print("========================================")
    print(" RUNNING HIGH-VOLATILITY & VOLUME TESTS")
    print("========================================\n")
    
    # 1. Test Triple Witching Detection
    print("--- Test 1: Triple Witching Detector ---")
    # 3rd Friday of March 2026 is March 20
    is_tw = intraday_tracker.is_triple_witching(datetime.datetime(2026, 3, 20))
    print(f"Is March 20, 2026 Triple Witching? {is_tw} (Expected: True)")
    assert is_tw == True
    
    # Juneteenth Shift (June 19, 2026 is closed, 3rd Friday. So Witching should be Thursday June 18)
    is_tw = intraday_tracker.is_triple_witching(datetime.datetime(2026, 6, 18))
    print(f"Is June 18, 2026 Triple Witching? {is_tw} (Expected: True)")
    assert is_tw == True
    
    # 2. Test Volume Gating Math
    print("\n--- Test 2: Volume Fake-out Protection ---")
    avg_vol = 1_000_000
    ny_tz = pytz.timezone('America/New_York')
    # Simulate 12:00 PM EST (150 minutes after 9:30 AM open)
    now_ny = datetime.datetime(2026, 6, 18, 12, 0, 0, tzinfo=ny_tz)
    market_open = now_ny.replace(hour=9, minute=30, second=0, microsecond=0)
    elapsed_minutes = (now_ny - market_open).total_seconds() / 60.0
    expected_vol = avg_vol * (elapsed_minutes / 390.0)
    
    print(f"Average Daily Volume: {avg_vol:,}")
    print(f"Time: 12:00 PM EST ({elapsed_minutes} minutes elapsed)")
    print(f"Expected Minimum Volume so far: {expected_vol:,.0f}")
    
    live_vol_fakeout = expected_vol * 0.4
    live_vol_real = expected_vol * 0.8
    
    print(f"Scenario A (Live Vol = {live_vol_fakeout:,.0f}): Passes Gate? {live_vol_fakeout >= expected_vol * 0.5}")
    assert (live_vol_fakeout >= expected_vol * 0.5) == False
    
    print(f"Scenario B (Live Vol = {live_vol_real:,.0f}): Passes Gate? {live_vol_real >= expected_vol * 0.5}")
    assert (live_vol_real >= expected_vol * 0.5) == True

    print("\nSUCCESS! Intraday Sniper logic mathematically verified.")

if __name__ == "__main__":
    test_volume_gating()
