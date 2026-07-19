import os
import subprocess
import sys

def run_qa_manager():
    print("=== AntiGravity Unified QA Manager ===")
    
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    python_exe = sys.executable
    
    qa_scripts = [
        "qa_api_health.py",
        "qa_auditor.py",
        "qa_dashboard_integrity.py",
        "qa_data_alignment.py",
        "qa_data_continuity_per_ticker.py",
        "qa_financial_audit.py",
        "qa_ledger_balance.py",
        "qa_logical_flows.py",
        "qa_task_auditor.py"
    ]
    
    failures = []
    
    for script in qa_scripts:
        script_path = os.path.join(BASE_DIR, script)
        if os.path.exists(script_path):
            print(f"\n--> Executing {script}...")
            result = subprocess.run([python_exe, script_path], cwd=BASE_DIR)
            if result.returncode != 0:
                print(f"\n[!] QA FAILED: {script} returned non-zero exit code: {result.returncode}")
                failures.append(script)
            else:
                print(f"\n[+] QA PASSED: {script}")
        else:
            print(f"\n[-] QA SKIPPED: {script} not found in {BASE_DIR}")
            
    print("\n==================================================")
    if failures:
        print("FINAL QA STATUS: FAIL")
        print(f"The following QA modules failed: {', '.join(failures)}")
        return False
    else:
        print("FINAL QA STATUS: 100% GREEN (ALL PASSED)")
        return True

if __name__ == "__main__":
    success = run_qa_manager()
    if not success:
        sys.exit(1)
    sys.exit(0)
