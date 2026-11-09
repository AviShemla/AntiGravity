import paramiko
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv()

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.getenv('VULTR_IP', '66.42.118.26'), username='root', password=os.getenv('VULTR_PASSWORD'), timeout=15)

def run_remote(cmd_str, timeout=25):
    print(f"=== CMD: {cmd_str} ===", flush=True)
    _, out, err = c.exec_command(cmd_str, timeout=timeout)
    print(out.read().decode('utf-8', 'replace'), flush=True)
    e = err.read().decode('utf-8', 'replace')
    if e:
        print("ERR:", e, flush=True)

# Check running intraday_tracker processes and keep only the first one if >1
fix_sniper_py = """
import psutil, os, sys, subprocess
sniper_pids = []
for p in psutil.process_iter(['pid', 'cmdline']):
    try:
        cmd = ' '.join(p.info['cmdline'] or [])
        if 'intraday_tracker.py' in cmd and 'forkserver' not in cmd and 'resource_tracker' not in cmd and 'bash -c' not in cmd:
            sniper_pids.append(p.info['pid'])
    except Exception:
        pass
sniper_pids.sort()
print('Active Sniper PIDs before dedup:', sniper_pids)
if len(sniper_pids) > 1:
    for pid in sniper_pids[1:]:
        print('Killing duplicate Sniper PID:', pid)
        try:
            os.kill(pid, 9)
        except Exception:
            pass
elif len(sniper_pids) == 0:
    log_f = open('/opt/antigravity/intraday_tracker.log', 'a')
    p = subprocess.Popen(['/opt/antigravity/venv/bin/python3', '-u', 'intraday_tracker.py'], cwd='/opt/antigravity', stdout=log_f, stderr=log_f, close_fds=True)
    print('Started Sniper PID:', p.pid)
sys.stdout.flush()
os._exit(0)
"""

sftp = c.open_sftp()
with sftp.file('/opt/antigravity/dedup_sniper.py', 'w') as f:
    f.write(fix_sniper_py)
sftp.close()

run_remote("cd /opt/antigravity && /opt/antigravity/venv/bin/python dedup_sniper.py")
run_remote("ps -ef | grep python | grep -v grep")
run_remote("tail -n 75 /opt/antigravity/intraday_tracker.log")
run_remote("cd /opt/antigravity && /opt/antigravity/venv/bin/python check_live_trade_day.py")

c.close()
sys.stdout.flush()
os._exit(0)
