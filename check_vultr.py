import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")
stdin, stdout, stderr = ssh.exec_command("ls -lh /opt/")
print(stdout.read().decode())
ssh.close()
