import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

script = """
cd /opt/antigravity
source venv/bin/activate
python -c "
from database_manager import execute_query
try:
    df = execute_query('SELECT persona, ticker, action, quantity, target_price FROM pending_orders')
    if df.empty: print('No Pending Orders')
    else: print(df.to_string())
except Exception as e:
    print('DB Error:', e)
"
"""
stdin, stdout, stderr = ssh.exec_command(script)
print(stdout.read().decode('utf-8').strip())
ssh.close()
