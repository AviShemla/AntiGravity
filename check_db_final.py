import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

script = """
import sys, os
sys.path.append("/opt/antigravity")
import database_manager
try:
    df = database_manager.execute_query("SELECT persona, MAX(date) FROM capital_ledgers GROUP BY persona")
    print(df.to_string())
except Exception as e:
    print(e)
os._exit(0)
"""
stdin, stdout, stderr = ssh.exec_command(f'cd /opt/antigravity && source venv/bin/activate && python -u -c "{script}"')
print("STDOUT:\n", stdout.read().decode('utf-8'))
ssh.close()
