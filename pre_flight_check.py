import subprocess
import sys
import datetime

def log_msg(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")

def run_qa_suite():
    log_msg("=== Initiating AntiGravity Pre-Flight QA Suite ===")
    
    try:
        # Run the full pytest suite
        result = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-v", "--disable-warnings"], capture_output=True, text=True)
        
        print(result.stdout)
        
        if result.returncode != 0:
            log_msg("CRITICAL: QA Suite Failed! Deployment Blocked.")
            print(result.stderr)
            sys.exit(1)
            
        log_msg("SUCCESS: All assertions passed. System is 100% Green and ready for deployment.")
        sys.exit(0)
        
    except FileNotFoundError:
        log_msg("ERROR: pytest is not installed or not found in PATH.")
        sys.exit(1)

if __name__ == "__main__":
    run_qa_suite()
