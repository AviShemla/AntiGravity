import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

stdin, stdout, stderr = ssh.exec_command("cd /opt/antigravity && source venv/bin/activate && nohup python -u master_pipeline.py > master_emergency.log 2>&1 &")
ssh.close()
