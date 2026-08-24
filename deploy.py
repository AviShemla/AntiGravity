import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password=__import__("os").environ["VULTR_ROOT_PASSWORD"])

script = """
cd /opt/antigravity
unzip -o /opt/vultr_sync.zip
systemctl restart ag-uvicorn
systemctl restart ag-sniper
systemctl restart ag-vix
source .venv/bin/activate || source venv/bin/activate
nohup python prefect_pipeline.py serve > prefect_daemon.log 2>&1 &
"""
ssh.exec_command(script)
ssh.close()
print("Deployed!")
