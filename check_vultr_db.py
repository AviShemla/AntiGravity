import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    ssh.connect('66.42.118.26', port=22, username='root', password=__import__("os").environ["VULTR_ROOT_PASSWORD"])
    stdin, stdout, stderr = ssh.exec_command('ls -la /opt/antigravity/financial_data/ag_pipeline_fallback.db')
    print("STDOUT:", stdout.read().decode('utf-8'))
    
    script = """import sqlite3
import pandas as pd
conn = sqlite3.connect('/opt/antigravity/financial_data/ag_pipeline_fallback.db')
print('PENDING ORDERS DATES:')
try:
    print(pd.read_sql_query('SELECT persona, date FROM pending_orders', conn))
except Exception as e:
    print('Error:', e)
conn.close()
"""
    stdin, stdout, stderr = ssh.exec_command('python3 -c "' + script.replace('\n', '; ') + '"')
    print("SQL OUTPUT:", stdout.read().decode('utf-8'))
    print("SQL ERR:", stderr.read().decode('utf-8'))
except Exception as e:
    print(f"Error: {e}")
finally:
    ssh.close()
