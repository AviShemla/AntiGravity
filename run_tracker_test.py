import sys
import os
import traceback

with open(r'C:\Users\AviShemla\AntiGravity\tracker_debug.txt', 'w') as f:
    f.write("Starting test...\n")
    f.flush()
    try:
        sys.path.insert(0, r'C:\Users\AviShemla\AntiGravity')
        import intraday_tracker
        f.write("Imported intraday_tracker\n")
        f.flush()
        
        f.write("Running execute_pending_orders...\n")
        f.flush()
        intraday_tracker.execute_pending_orders(is_eod_fallback=True, target_date='2026-06-23')
        f.write("Done execute_pending_orders!\n")
        f.flush()
    except Exception as e:
        f.write("Error: " + str(e) + "\n")
        f.write(traceback.format_exc() + "\n")
        f.flush()
