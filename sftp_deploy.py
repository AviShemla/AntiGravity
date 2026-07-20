import paramiko
import os

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', username='root', password='M,w5_=k@eHA!ecEK')

commands = [
    'ps aux | grep watchdog',
    'cd /opt/antigravity && nohup ./venv/bin/python3 -m uvicorn server:app --host 0.0.0.0 --port 80 > uvicorn.log 2>&1 &'
]

for cmd in commands:
    print(f"Executing: {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    print("STDOUT:", stdout.read().decode())
    print("STDERR:", stderr.read().decode())

ssh.close()
