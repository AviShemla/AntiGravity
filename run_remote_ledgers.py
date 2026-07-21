import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

sftp = ssh.open_sftp()
sftp.put("check_ledgers.py", "/opt/antigravity/check_ledgers.py")
sftp.close()

stdin, stdout, stderr = ssh.exec_command("cd /opt/antigravity && source venv/bin/activate && python -u check_ledgers.py")
print("STDOUT:", stdout.read().decode('utf-8'))
ssh.close()
