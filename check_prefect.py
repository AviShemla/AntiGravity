import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

stdin, stdout, stderr = ssh.exec_command("grep -irE 'antigravity_nightly_flow|master_pipeline|ERROR|FAIL' /opt/antigravity/*.log | tail -n 40")
print("STDOUT:\n", stdout.read().decode('utf-8'))
ssh.close()
