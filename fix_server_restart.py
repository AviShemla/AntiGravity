import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', username='root', password='M,w5_=k@eHA!ecEK')

sftp = ssh.open_sftp()
sftp.put('server.py', '/opt/antigravity/server.py')
print("Uploaded server.py")
sftp.close()

stdin, stdout, stderr = ssh.exec_command("pkill -f uvicorn ; cd /opt/antigravity && nohup ./venv/bin/python3 -m uvicorn server:app --host 0.0.0.0 --port 80 > uvicorn.log 2>&1 &")
print("Restarted uvicorn.")
ssh.close()
