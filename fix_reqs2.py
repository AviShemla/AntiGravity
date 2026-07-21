import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

script = """
cd /opt/antigravity
source venv/bin/activate
echo "Installing core dependencies explicitly..."
apt-get install -y python3-dev build-essential
pip install pandas yfinance prefect uvicorn fastapi pydantic sqlalchemy pytz schedule psutil pymc PyYAML paramiko python-dotenv pandas_market_calendars
echo "Running QA Audit again..."
python prefect_pipeline.py qa
"""
print("Executing robust fix script on Vultr...")
stdin, stdout, stderr = ssh.exec_command(script)
exit_status = stdout.channel.recv_exit_status()
print(stdout.read().decode())
err = stderr.read().decode()
if err: print("STDERR:", err)
ssh.close()
print(f"Fix process complete! Exit status: {exit_status}")
