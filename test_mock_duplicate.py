import subprocess
import time
import os
import sqlite3
import json
import sys

BASE_DIR = r"C:\Users\AviShemla\AntiGravity"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def setup_mock_db_and_json():
    print("Setting up mock database and JSON...")
    db_path = os.path.join(SCRIPT_DIR, "mock_antigravity.db")
    if os.path.exists(db_path):
        os.remove(db_path)
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS dummy_predictions (id INTEGER, value INTEGER, label TEXT)")
    conn.commit()
    conn.close()

    json_path = os.path.join(SCRIPT_DIR, "mock_tmp_pred.json")
    data = {
        "id": 1,
        "value": 1.2345,  # float, but DB is INTEGER -> silent truncation
        "label": "test"
    }
    with open(json_path, 'w') as f:
        json.dump(data, f)
        
    return db_path, json_path

def main():
    db_path, json_path = setup_mock_db_and_json()
    
    print("Spawning fake duplicate pipelines (mocking run_backtests.py)...")
    cmd = [sys.executable, "-c", "import time; time.sleep(15)", "run_backtests.py"]
    
    # We spawn two mock processes to ensure a collision is detected
    p1 = subprocess.Popen(cmd)
    p2 = subprocess.Popen(cmd)
    
    print("Waiting for fake processes to initialize...")
    time.sleep(2)
    
    print("Running qa_auditor.py...")
    auditor_path = os.path.join(SCRIPT_DIR, "qa_auditor.py")
    
    # Run auditor against the mock db and json
    subprocess.run([sys.executable, auditor_path, "--db-path", db_path, "--json-path", json_path, "--mock"])
    
    print("Cleaning up fake processes...")
    p1.terminate()
    p2.terminate()
    
    # Print the log output for verification
    log_file = os.path.join(SCRIPT_DIR, "qa_audit.log")
    print(f"\n--- CONTENTS OF {log_file} ---")
    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            print(f.read())
    else:
        print("Log file not found.")
    print("--- END OF LOG ---\n")
    print("Done. Verification complete.")

if __name__ == "__main__":
    main()
