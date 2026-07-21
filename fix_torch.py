import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

print("Installing PyTorch...")
stdin, stdout, stderr = ssh.exec_command("cd /opt/antigravity && source venv/bin/activate && pip install torch --index-url https://download.pytorch.org/whl/cpu")
print("STDOUT:\n", stdout.read().decode('utf-8'))

print("Relaunching Force Script...")
ssh.exec_command("cd /opt/antigravity && source venv/bin/activate && nohup python -u force_run_script.py > force_stock.log 2>&1 &")
ssh.close()
