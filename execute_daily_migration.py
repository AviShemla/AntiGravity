import os
import sys
import subprocess
import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON_EXE = r"C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\python.exe"

def log(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")

def run_script(script_name):
    script_path = os.path.join(BASE_DIR, script_name)
    log(f"Running {script_name}...")
    result = subprocess.run([PYTHON_EXE, script_path], cwd=BASE_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"ERROR: {script_name} failed!\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}")
        return False
    return True

def main():
    log("=== Starting Automated Daily Migration Backup ===")
    
    # 1. Run QA Tests
    # We check if QA_Results.txt ends with "PASSED" or we just rely on return code if we had one.
    # run_qa_tests.py doesn't return an error code by default, so we read QA_Results.txt
    log("Executing full QA Audit...")
    subprocess.run([PYTHON_EXE, os.path.join(BASE_DIR, "run_qa_tests.py")], cwd=BASE_DIR)
    
    qa_results_path = os.path.join(BASE_DIR, "QA_Results.txt")
    if os.path.exists(qa_results_path):
        with open(qa_results_path, "r") as f:
            content = f.read()
        if "FAILED" in content or "ERROR" in content:
            log("QA Audit FAILED! Aborting git commit and migration backup.")
            os._exit(1)
        else:
            log("QA Audit PASSED 100% GREEN.")
    else:
        log("QA_Results.txt missing! Aborting.")
        os._exit(1)
        
    # 2. Run Migration Zipper (Google Drive)
    if not run_script("zip_migration.py"):
        os._exit(1)
        
    # 3. Git Commit and Push
    log("Committing to Git...")
    try:
        subprocess.run(["git", "add", "."], cwd=BASE_DIR, check=True)
        # git commit might fail if there's nothing to commit
        subprocess.run(["git", "commit", "-m", f"Automated Daily Migration Backup - {datetime.date.today()}"], cwd=BASE_DIR)
        subprocess.run(["git", "push"], cwd=BASE_DIR, check=True)
        log("Git Push successful.")
    except Exception as e:
        log(f"Git operations warning/error: {e}")
        
    # 4. Send Email Notification
    if not run_script("send_migration_email.py"):
        os._exit(1)
        
    log("=== Daily Migration Backup Completed Successfully ===")

if __name__ == "__main__":
    main()
