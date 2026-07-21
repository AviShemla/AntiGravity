import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

# 1. Install xlsxwriter
ssh.exec_command("cd /opt/antigravity && source venv/bin/activate && pip install xlsxwriter openpyxl")

# 2. Run the final two scripts (export & virtual_broker)
script = """
import subprocess
import os

BASE_DIR = "/opt/antigravity"
python_exe = os.path.join(BASE_DIR, "venv/bin/python")

try:
    print("Running Export...")
    subprocess.run([python_exe, os.path.join(BASE_DIR, "export_bayesian_scorecard_formatted.py")], cwd=BASE_DIR, check=True)
    print("Running Virtual Broker...")
    subprocess.run([python_exe, os.path.join(BASE_DIR, "virtual_broker.py")], cwd=BASE_DIR, check=True)
    print("SUCCESS: Injection Complete")
except Exception as e:
    print(e)
"""

stdin, stdout, stderr = ssh.exec_command(f'cd /opt/antigravity && source venv/bin/activate && python -u -c "{script}"')
print("STDOUT:\n", stdout.read().decode('utf-8'))

ssh.close()
