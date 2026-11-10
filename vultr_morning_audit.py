import paramiko
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv()

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.getenv('VULTR_IP', '66.42.118.26'), username='root', password=os.getenv('VULTR_PASSWORD'), timeout=15)

def run_remote(cmd_str, timeout=45):
    print(f"=== CMD: {cmd_str} ===", flush=True)
    _, out, err = c.exec_command(cmd_str, timeout=timeout)
    print(out.read().decode('utf-8', 'replace'), flush=True)
    e = err.read().decode('utf-8', 'replace')
    if e:
        print("ERR:", e, flush=True)

# Append os._exit(0) to fix_arena_volatility_envelope.py on Vultr if missing
run_remote("grep -q 'os._exit(0)' /opt/antigravity/fix_arena_volatility_envelope.py || echo 'import os, sys; sys.stdout.flush(); os._exit(0)' >> /opt/antigravity/fix_arena_volatility_envelope.py")
run_remote("pkill -9 -f fix_arena_volatility_envelope.py || true")

run_remote("cd /opt/antigravity && /opt/antigravity/venv/bin/python fix_arena_volatility_envelope.py")
run_remote("cd /opt/antigravity && /opt/antigravity/venv/bin/python sync_20261106_eod.py")
run_remote("cd /opt/antigravity && /opt/antigravity/venv/bin/python prod_vs_shadow_tracker.py 2026-11-09")
run_remote("cd /opt/antigravity && /opt/antigravity/venv/bin/python qa_dashboard_integrity.py")
run_remote("cd /opt/antigravity && /opt/antigravity/venv/bin/python qa_manager.py", timeout=90)

c.close()
sys.stdout.flush()
os._exit(0)
