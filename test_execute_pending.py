import intraday_tracker
import datetime
import pytz

now_ny = datetime.datetime.now(pytz.timezone('America/New_York'))
eod_fallback_time = now_ny.replace(hour=15, minute=55, second=0, microsecond=0)
is_eod = now_ny >= eod_fallback_time

print(f"Running execute_pending_orders(is_eod_fallback={is_eod})...")
intraday_tracker.execute_pending_orders(is_eod_fallback=is_eod)
print("Done.")
