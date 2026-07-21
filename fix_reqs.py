import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

script = """
cd /opt/antigravity
# Remove Windows-specific packages from requirements.txt
sed -i '/pywin32/d' requirements.txt
source venv/bin/activate
echo "Installing cleaned requirements..."
pip install -r requirements.txt
pip install psutil
echo "Running QA Audit..."
python prefect_pipeline.py qa
"""
print("Executing fix script on Vultr...")
stdin, stdout, stderr = ssh.exec_command(script)
exit_status = stdout.channel.recv_exit_status()
print(stdout.read().decode())
err = stderr.read().decode()
if err: print("STDERR:", err)
ssh.close()
print(f"Fix process complete! Exit status: {exit_status}")
