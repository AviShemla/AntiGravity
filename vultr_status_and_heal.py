import paramiko
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv()

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.getenv('VULTR_IP', '66.42.118.26'), username='root', password=os.getenv('VULTR_PASSWORD'), timeout=15)

def run_remote(cmd_str):
    print(f"=== CMD: {cmd_str} ===", flush=True)
    _, out, err = c.exec_command(cmd_str, timeout=20)
    print(out.read().decode('utf-8', 'replace'), flush=True)
    e = err.read().decode('utf-8', 'replace')
    if e:
        print("ERR:", e, flush=True)

run_remote("ps -ef | grep python | grep -v grep")
run_remote("cd /opt/antigravity && /opt/antigravity/venv/bin/python -c \"import os, sys, database_manager as db; db.update_continuity('etf_pipeline', '2026-11-06'); print(db.execute_query('SELECT * FROM process_continuity')); sys.stdout.flush(); os._exit(0)\"")
run_remote("cd /opt/antigravity && /opt/antigravity/venv/bin/python qa_task_auditor.py")
run_remote("tail -n 25 /opt/antigravity/prefect_serve.log")

c.close()
sys.stdout.flush()
os._exit(0)
