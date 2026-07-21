import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

sftp = ssh.open_sftp()
sftp.put(r"C:\Users\AviShemla\AntiGravity\prefect_pipeline.py", "/opt/antigravity/prefect_pipeline.py")
sftp.close()

script = """
pkill -f "python prefect_pipeline.py serve"
cd /opt/antigravity && source venv/bin/activate && python prefect_pipeline.py serve > prefect.log 2>&1 &
"""
ssh.exec_command(script)
print("Prefect Orchestrator successfully updated and restarted!")
ssh.close()
