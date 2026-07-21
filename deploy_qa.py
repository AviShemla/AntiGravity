import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

sftp = ssh.open_sftp()
sftp.put("system_qa_auditor.py", "/opt/antigravity/system_qa_auditor.py")
sftp.close()

ssh.close()
