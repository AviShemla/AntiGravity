import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

script = """
import os, sys, traceback
sys.path.append('/opt/antigravity')
from database_manager import execute_query
try:
    df = execute_query('SELECT * FROM process_continuity')
    print(df.to_string())
except Exception as e: print(e)
os._exit(0)
"""

stdin, stdout, stderr = ssh.exec_command(f'cd /opt/antigravity && source venv/bin/activate && python -u -c "{script}"')
print("STDOUT:\n", stdout.read().decode('utf-8'))
ssh.close()
