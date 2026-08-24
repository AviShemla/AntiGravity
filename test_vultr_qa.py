import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password=__import__("os").environ["VULTR_ROOT_PASSWORD"])

stdin, stdout, stderr = ssh.exec_command("cd /opt/antigravity && source .venv/bin/activate || source venv/bin/activate && python prefect_pipeline.py qa")
print(stdout.read().decode())
print(stderr.read().decode())
ssh.close()
