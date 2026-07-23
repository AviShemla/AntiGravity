import paramiko
import os

print("Deploying patched prod_vs_shadow_tracker.py to Vultr...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

sftp = ssh.open_sftp()
local_path = "prod_vs_shadow_tracker.py"
remote_path = "/opt/antigravity/prod_vs_shadow_tracker.py"
if os.path.exists(local_path):
    sftp.put(local_path, remote_path)
sftp.close()

print("Purging rogue 2026-07-23 row from Vultr CSV...")
purge_script = """
import json
import pandas as pd
import os

CSV_PATH = '/opt/antigravity/financial_data/Prod_vs_Shadow_Results_MASTER.csv'
STATE_PATH = '/opt/antigravity/financial_data/prod_shadow_state.json'

if os.path.exists(CSV_PATH):
    df = pd.read_csv(CSV_PATH)
    if 'Date' in df.columns:
        df = df[df['Date'] != '2026-07-23']
        df.to_csv(CSV_PATH, index=False)
        
if os.path.exists(STATE_PATH):
    with open(STATE_PATH, 'r') as f:
        st = json.load(f)
    if st.get('last_date') == '2026-07-23':
        st['last_date'] = '2026-07-22'
        with open(STATE_PATH, 'w') as f:
            json.dump(st, f)
"""
stdin, stdout, stderr = ssh.exec_command("cat > /tmp/purge_rogue.py << 'EOF'\n" + purge_script + "\nEOF")
stdout.read()

print("Running purge script on Vultr...")
stdin, stdout, stderr = ssh.exec_command("/opt/antigravity/venv/bin/python3 /tmp/purge_rogue.py")
print(stdout.read().decode())
print(stderr.read().decode())

print("Restarting Uvicorn...")
ssh.exec_command("pkill -9 -f uvicorn")
ssh.exec_command("cd /opt/antigravity && nohup ./venv/bin/python3 -m uvicorn server:app --host 0.0.0.0 --port 80 > /dev/null 2>&1 &")

ssh.close()
print("Deployment and purge complete.")
