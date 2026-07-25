import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', port=22, username='root', password='M,w5_=k@eHA!ecEK')

print("Starting new sniper with nohup...")
i, o, e = ssh.exec_command('cd /opt/antigravity && nohup /opt/antigravity/venv/bin/python -u intraday_tracker.py > intraday_sniper.log 2>&1 &')
import time
time.sleep(2)
ssh.close()
