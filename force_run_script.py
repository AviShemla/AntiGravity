import sys, os
sys.path.append("/opt/antigravity")
import laptop_catchup_controller
import database_manager

print("=== FORCE EXECUTING MASTER PIPELINE FOR 2026-07-20 ===")
# Monkey patch the logic bug so it is forced to process today
laptop_catchup_controller.get_missed_dates = lambda x: ['2026-07-20']

try:
    laptop_catchup_controller.catchup_master_pipeline()
    print("FINISHED EXECUTING MASTER PIPELINE")
except Exception as e:
    print(f"FATAL ERROR: {e}")
    import traceback
    traceback.print_exc()
os._exit(0)
