import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', username='root', password='M,w5_=k@eHA!ecEK')

sftp = ssh.open_sftp()
sftp.put('server.py', '/opt/antigravity/server.py')
print("Uploaded server.py")
sftp.close()

stdin, stdout, stderr = ssh.exec_command("systemctl restart antigravity")
print(stdout.read().decode())
print(stderr.read().decode())
ssh.close()
