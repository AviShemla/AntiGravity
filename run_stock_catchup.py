import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

stdin, stdout, stderr = ssh.exec_command("cd /opt/antigravity && source venv/bin/activate && nohup python -u laptop_catchup_controller.py master > stock_catchup.log 2>&1 &")
ssh.close()
