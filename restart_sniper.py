import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', port=22, username='root', password='M,w5_=k@eHA!ecEK')

print("Killing old sniper...")
ssh.exec_command('pkill -f intraday_tracker.py')

import time
time.sleep(2)

print("Starting new sniper...")
i, o, e = ssh.exec_command('cd /opt/antigravity && /opt/antigravity/venv/bin/python -c "import prefect_pipeline; prefect_pipeline.ensure_intraday_sniper()"')
print(o.read().decode('utf-8'))
if e:
    print(e.read().decode('utf-8'))

ssh.close()
