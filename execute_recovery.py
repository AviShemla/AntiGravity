import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', username='root', password='M,w5_=k@eHA!ecEK')

print("1. Killing all python zombie processes...")
ssh.exec_command("pkill -9 -f python")
time.sleep(2)

print("2. Starting Uvicorn API Server...")
ssh.exec_command("cd /opt/antigravity && nohup ./venv/bin/python3 -m uvicorn server:app --host 0.0.0.0 --port 80 > uvicorn.log 2>&1 &")
time.sleep(3)

print("3. Starting Master Watchdog...")
ssh.exec_command("cd /opt/antigravity && nohup ./venv/bin/python3 master_watchdog.py > watchdog.log 2>&1 &")
time.sleep(2)

print("4. Verifying running processes...")
stdin, stdout, stderr = ssh.exec_command("ps aux | grep python")
print(stdout.read().decode())

ssh.close()
