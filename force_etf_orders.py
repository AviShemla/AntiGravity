import os
import sys
import multiprocessing
import time
import json
import etf_virtual_broker

def generate():
    try:
        etf_virtual_broker.run_etf_virtual_broker()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    print("Starting ETF Broker in isolated process to prevent deadlocks...")
    p = multiprocessing.Process(target=generate)
    p.start()
    p.join(timeout=120)
    if p.is_alive():
        print("Timeout reached! Terminating process...")
        p.terminate()
        p.join()
    print("Done! Verifying Pending_Orders.json...")
    try:
        with open('financial_data/Pending_Orders.json', 'r') as f:
            data = json.load(f)
            dates = [v.get('Date', 'N/A') for k, v in data.items()]
            print(f"Current Dates in JSON: {set(dates)}")
    except Exception as e:
        print(f"Could not read JSON: {e}")
    import sys; sys.stdout.flush(); os._exit(0)
