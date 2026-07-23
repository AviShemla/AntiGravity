import paramiko
import sys

def check_vultr():
    print("=== VULTR QA AUDIT ===")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")
    except Exception as e:
        print(f"FAILED TO CONNECT TO VULTR: {e}")
        sys.exit(1)
        
    print("\n--- Running Python Processes ---")
    stdin, stdout, stderr = ssh.exec_command("ps aux | grep python")
    processes = stdout.read().decode('utf-8')
    print(processes)
    
    if "intraday_tracker.py" not in processes:
        print("CRITICAL QA FAILURE: intraday_tracker.py is NOT running on Vultr!")
    else:
        print("PASS: Intraday Sniper is running on Vultr.")
        
    if "vix_monitor.py" not in processes:
        print("CRITICAL QA FAILURE: vix_monitor.py is NOT running on Vultr!")
    else:
        print("PASS: VIX Monitor is running on Vultr.")
        
    if "prefect_pipeline.py serve" not in processes:
        print("CRITICAL QA FAILURE: Prefect Orchestrator is NOT serving on Vultr!")
    else:
        print("PASS: Prefect is serving on Vultr.")
        
    print("\n--- Tail of prefect_serve.log ---")
    stdin, stdout, stderr = ssh.exec_command("tail -n 20 /opt/antigravity/prefect_serve.log")
    print(stdout.read().decode('utf-8'))
    print(stderr.read().decode('utf-8'))
    
    ssh.close()

if __name__ == "__main__":
    check_vultr()
