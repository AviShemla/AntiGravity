import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', username='root', password='M,w5_=k@eHA!ecEK')
stdin, stdout, stderr = ssh.exec_command("cat /opt/antigravity/uvicorn.log | tail -n 50")
print(stdout.read().decode())
ssh.close()
