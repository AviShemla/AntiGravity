import os
import sys
import subprocess
import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON_EXE = sys.executable

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
    
    # 1. Run Unified QA Manager
    log("Executing Unified QA Manager Audit...")
    qa_res = subprocess.run([PYTHON_EXE, os.path.join(BASE_DIR, "qa_manager.py")], cwd=BASE_DIR)
    if qa_res.returncode != 0:
        log("QA Audit FAILED! Aborting git commit and migration backup.")
        os._exit(1)
    log("QA Audit PASSED 100% GREEN.")
        
    # 2. Run Migration Zipper if on Windows (or skip local zip on Linux cloud host)
    if os.name == "nt" and os.path.exists(os.path.join(BASE_DIR, "zip_migration.py")):
        if not run_script("zip_migration.py"):
            log("Warning: zip_migration.py returned non-zero.")
        
    # 3. Git Commit and Push
    log("Committing to Git...")
    try:
        subprocess.run(["git", "add", "."], cwd=BASE_DIR)
        subprocess.run(["git", "commit", "-m", f"Automated Daily Migration Backup - {datetime.date.today()}"], cwd=BASE_DIR)
        subprocess.run(["git", "push"], cwd=BASE_DIR)
        log("Git Push completed.")
    except Exception as e:
        log(f"Git operations warning/error: {e}")
        
    log("=== Daily Migration Backup Completed Successfully ===")
    sys.stdout.flush()
    os._exit(0)

if __name__ == "__main__":
    main()
