import paramiko
import time
import json
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print("Connecting to Vultr...")
ssh.connect("66.42.118.26", port=22, username="root", password=__import__("os").environ["VULTR_ROOT_PASSWORD"])
print("Triggering ETF Pipeline on Vultr... (this will take 1-2 minutes)")
stdin, stdout, stderr = ssh.exec_command("cd /opt/antigravity && source venv/bin/activate && python -u etf_daily_pipeline.py")
for line in iter(stdout.readline, ""):
    print(line, end="")
print(stderr.read().decode('utf-8'))

# Now download the JSON
print("Downloading Pending_Orders.json from Vultr...")
sftp = ssh.open_sftp()
sftp.get('/opt/antigravity/financial_data/Pending_Orders.json', 'C:/Users/AviShemla/AntiGravity/financial_data/Pending_Orders.json')
sftp.close()
ssh.close()
print("DONE!")
