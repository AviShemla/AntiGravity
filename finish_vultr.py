import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

def exec_cmd(cmd):
    print(f"Executing: {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8')
    err = stderr.read().decode('utf-8')
    if exit_status != 0:
        print(f"ERROR: {err}")
    return out

print("Unzipping on Vultr...")
exec_cmd("apt-get install -y unzip")
exec_cmd("unzip -o /opt/vultr_sync.zip -d /opt/antigravity/")
print("Restarting systemd services with new code...")
exec_cmd("systemctl restart ag-uvicorn")
exec_cmd("systemctl restart ag-sniper")
exec_cmd("systemctl restart ag-vix")
print("Deploying Prefect Flows natively on Vultr...")
exec_cmd("cd /opt/antigravity && source venv/bin/activate && python prefect_pipeline.py serve > prefect.log 2>&1 &")
ssh.close()
print("FULL VULTR DEPLOYMENT AND ORCHESTRATION COMPLETE!")
