import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

sftp = ssh.open_sftp()
sftp.put(r"C:\Users\AviShemla\AntiGravity\qa_financial_audit.py", "/opt/antigravity/qa_financial_audit.py")
sftp.close()

stdin, stdout, stderr = ssh.exec_command("cd /opt/antigravity && source venv/bin/activate && python prefect_pipeline.py qa")
print(stdout.read().decode('utf-8', errors='ignore'))
ssh.close()
