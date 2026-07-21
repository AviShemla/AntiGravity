import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

script = """
cd /opt/antigravity
echo "Wiping corrupted Windows venv..."
rm -rf venv .venv
echo "Building native Linux venv..."
python3 -m venv venv
source venv/bin/activate
echo "Upgrading pip..."
pip install --upgrade pip
echo "Installing dependencies..."
pip install -r requirements.txt
pip install prefect
echo "Environment Rebuilt! Restarting Daemons..."
systemctl restart ag-uvicorn
systemctl restart ag-sniper
systemctl restart ag-vix
echo "Restarting Prefect Server..."
nohup python prefect_pipeline.py serve > prefect_daemon.log 2>&1 &
echo "Running QA Audit again..."
python prefect_pipeline.py qa
"""
ssh.exec_command(script)
ssh.close()
print("Rebuild process triggered!")
