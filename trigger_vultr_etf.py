import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password=__import__("os").environ["VULTR_ROOT_PASSWORD"])
print("Connected to Vultr. Triggering ETF Live Pipeline...")
stdin, stdout, stderr = ssh.exec_command("cd /opt/antigravity && source venv/bin/activate && python -u etf_daily_pipeline.py")
for line in iter(stdout.readline, ""):
    print(line, end="")
print("STDERR:", stderr.read().decode('utf-8'))
ssh.close()
