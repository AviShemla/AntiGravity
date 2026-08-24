import paramiko
import sys

def check_vultr():
    print("=== VULTR QA AUDIT ===")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect("66.42.118.26", port=22, username="root", password=__import__("os").environ["VULTR_ROOT_PASSWORD"])
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
        
    prefect_server_running = "prefect server start" in processes
    prefect_pipeline_running = "prefect_pipeline.py" in processes

    if not prefect_server_running and not prefect_pipeline_running:
        print("CRITICAL QA FAILURE: Prefect Orchestrator is NOT running on Vultr!")
        print("--- INITIATING AUTO-HEAL PROTOCOL ---")
        print("1. Hunting Zombies...")
        ssh.exec_command("/opt/antigravity/venv/bin/python /opt/antigravity/clean_ghosts.py")
        print("2. Restarting Prefect Server Daemon...")
        ssh.exec_command("source /opt/antigravity/venv/bin/activate && nohup prefect server start > /opt/antigravity/prefect_server_daemon.log 2>&1 &")
        import time; time.sleep(5)
        print("3. Restarting Pipeline Service...")
        ssh.exec_command("source /opt/antigravity/venv/bin/activate && nohup python /opt/antigravity/prefect_pipeline.py serve > /opt/antigravity/prefect_serve.log 2>&1 &")
        print("PASS: Auto-Heal complete. Prefect Orchestrator has been restarted.")
    elif prefect_server_running and not prefect_pipeline_running:
        print("WARNING: Prefect server is running but pipeline serve is missing. Restarting pipeline only...")
        ssh.exec_command("source /opt/antigravity/venv/bin/activate && nohup python /opt/antigravity/prefect_pipeline.py serve > /opt/antigravity/prefect_serve.log 2>&1 &")
        print("PASS: Pipeline serve restarted.")
    else:
        print("PASS: Prefect is fully serving on Vultr (server + pipeline both confirmed).")

        
    print("\n--- Tail of prefect_serve.log ---")
    stdin, stdout, stderr = ssh.exec_command("tail -n 20 /opt/antigravity/prefect_serve.log")
    print(stdout.read().decode('utf-8'))
    print(stderr.read().decode('utf-8'))
    
    ssh.close()

if __name__ == "__main__":
    check_vultr()
