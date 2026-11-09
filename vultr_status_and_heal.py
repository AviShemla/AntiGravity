import paramiko
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv()

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.getenv('VULTR_IP', '66.42.118.26'), username='root', password=os.getenv('VULTR_PASSWORD'), timeout=15)

sftp = c.open_sftp()
for f in ['database_manager.py', 'intraday_tracker.py', 'prefect_pipeline.py', 'qa_task_auditor.py']:
    sftp.put(f, f'/opt/antigravity/{f}')
sftp.close()

_, out, err = c.exec_command("cd /opt/antigravity && /opt/antigravity/venv/bin/python qa_task_auditor.py", timeout=25)
print(out.read().decode('utf-8', 'replace'), flush=True)
e = err.read().decode('utf-8', 'replace')
if e:
    print("ERR:", e, flush=True)
c.close()
sys.stdout.flush()
os._exit(0)
