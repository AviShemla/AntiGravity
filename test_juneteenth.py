import pandas_market_calendars as mcal
import pandas as pd

def test_juneteenth():
    print("\n--- Testing NYSE Holiday Calendar Engine ---")
    nyse = mcal.get_calendar('NYSE')
    
    # Test a known valid trading day (June 15, 2026 - Monday)
    valid_june15 = nyse.valid_days(start_date='2026-06-15', end_date='2026-06-15')
    print(f"Is June 15, 2026 open? {'YES' if len(valid_june15) > 0 else 'NO'}")
    assert len(valid_june15) > 0
    
    # Test Juneteenth (June 19, 2026 - Friday)
    valid_june19 = nyse.valid_days(start_date='2026-06-19', end_date='2026-06-19')
    print(f"Is June 19, 2026 open? {'YES' if len(valid_june19) > 0 else 'NO'}")
    assert len(valid_june19) == 0
    
    # Test July 4th (July 3 observed in 2026 - Friday)
    valid_july3 = nyse.valid_days(start_date='2026-07-03', end_date='2026-07-03')
    print(f"Is July 3, 2026 (Independence Day Observed) open? {'YES' if len(valid_july3) > 0 else 'NO'}")
    assert len(valid_july3) == 0
    
    print("\nSUCCESS! The AntiGravity engine mathematically recognizes US Market Holidays.")

if __name__ == "__main__":
    test_juneteenth()
