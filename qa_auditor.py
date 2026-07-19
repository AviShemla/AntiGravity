import os
import sys
import psutil
import json
import sqlite3
import argparse
import logging

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qa_audit.log")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def log_critical(msg):
    logging.critical(msg)
    print(f"CRITICAL: {msg}")

def check_process_locks(mock=False):
    """
    Scans the Windows process tree for master_pipeline.py and run_backtests.py.
    Verifies they hold their .lock files.
    Flags duplicate ghost processes.
    """
    target_scripts = ['master_pipeline.py', 'run_backtests.py']
    process_counts = {script: 0 for script in target_scripts}
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline')
            if not cmdline:
                continue
            
            cmd_str = ' '.join(cmdline).lower()
            
            for script in target_scripts:
                if script.lower() in cmd_str and 'python' in cmd_str:
                    # Ignore the auditor itself
                    if 'qa_auditor.py' not in cmd_str:
                        process_counts[script] += 1
                    
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    for script, count in process_counts.items():
        if count > 1:
            log_critical(f"OS SCHEDULING CONFLICT: {count} instances of {script} detected! Ghost process overlap.")
        
        if count >= 1:
            lock_file = os.path.join(BASE_DIR, script.replace('.py', '.lock'))
            if not os.path.exists(lock_file):
                log_critical(f"ARCHITECTURAL LOCK MISSING: {script} is running but {lock_file} was not found.")

def check_data_continuity(db_path, json_path):
    """
    Verifies that the RAM payloads dumped to tmp_pred_CHAMPION.json successfully map 
    to the SQLite antigravity.db schema without any silent Pandas datatype truncation.
    """
    if not os.path.exists(json_path):
        return
        
    if not os.path.exists(db_path):
        return

    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
    except json.JSONDecodeError:
        log_critical(f"JSON Decode Error for {json_path}")
        return

    if not data:
        return

    if isinstance(data, dict):
        sample = data
    elif isinstance(data, list) and len(data) > 0:
        sample = data[0]
    else:
        return

    expected_types = {}
    for key, val in sample.items():
        if isinstance(val, bool):
            expected_types[key] = 'INTEGER'
        elif isinstance(val, int):
            expected_types[key] = 'INTEGER'
        elif isinstance(val, float):
            expected_types[key] = 'REAL'
        else:
            expected_types[key] = 'TEXT'

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cursor.fetchall()]
        
        if not tables:
            conn.close()
            return
            
        for table in tables:
            cursor.execute(f"PRAGMA table_info({table});")
            columns = cursor.fetchall()
            
            db_schema = {col[1]: col[2].upper() for col in columns}
            
            mismatches = []
            checked_columns = 0
            for key, expected_type in expected_types.items():
                if key in db_schema:
                    checked_columns += 1
                    actual_type = db_schema[key]
                    if expected_type == 'REAL' and actual_type == 'INTEGER':
                        mismatches.append(f"Silent truncation risk: JSON '{key}' is float, but DB schema is {actual_type}.")
                    elif expected_type == 'TEXT' and actual_type in ('INTEGER', 'REAL'):
                        mismatches.append(f"Type mismatch: JSON '{key}' is string, but DB schema is {actual_type}.")

            if mismatches and checked_columns > 0:
                log_critical(f"DATA CONTINUITY MISMATCH in table '{table}': " + " | ".join(mismatches))
                
        conn.close()
    except Exception as e:
        log_critical(f"Database verification failed: {e}")

def main():
    parser = argparse.ArgumentParser(description="System QA & Architecture Auditor")
    parser.add_argument('--db-path', type=str, default=os.path.join(BASE_DIR, "antigravity.db"))
    parser.add_argument('--json-path', type=str, default=os.path.join(BASE_DIR, "tmp_pred_CHAMPION.json"))
    parser.add_argument('--mock', action='store_true', help="Run in mock test mode")
    
    args = parser.parse_args()
    
    try:
        check_process_locks(mock=args.mock)
        check_data_continuity(args.db_path, args.json_path)
    except Exception as e:
        log_critical(f"QA Auditor encountered an internal exception: {e}")

if __name__ == "__main__":
    main()
