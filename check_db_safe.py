import paramiko
import sys
sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

# 1. Check DB
script = """
import sys, os
sys.path.append("/opt/antigravity")
import database_manager
try:
    df = database_manager.execute_query("SELECT persona, MAX(date) FROM capital_ledgers GROUP BY persona")
    print("--- DB Ledgers ---")
    print(df.to_string())
except Exception as e:
    print(e)
os._exit(0)
"""
stdin, stdout, stderr = ssh.exec_command(f'cd /opt/antigravity && source venv/bin/activate && python -u -c "{script}"')
print(stdout.read().decode('utf-8', errors='replace'))

# 2. Check Logs
stdin, stdout, stderr = ssh.exec_command("tail -n 20 /opt/antigravity/force_stock.log")
print("--- LOG ---")
print(stdout.read().decode('utf-8', errors='replace'))

ssh.close()
