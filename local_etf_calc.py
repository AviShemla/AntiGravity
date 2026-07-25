import sys
import traceback
import etf_virtual_broker
try:
    print("Running ETF Broker locally...")
    etf_virtual_broker.target_date_for_ledger = "2026-07-22"
    etf_virtual_broker.run_etf_virtual_broker()
    print("SUCCESSFULLY GENERATED ORDERS!")
except Exception as e:
    print("CRASHED!")
    traceback.print_exc()
import os
import sys; sys.stdout.flush(); os._exit(0)
