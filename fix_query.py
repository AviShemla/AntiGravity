import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

script = """
import os, sys, traceback
sys.path.append("/opt/antigravity")
from database_manager import execute_query

try:
    print("--- TRANSACTION LOG ---")
    df = execute_query("SELECT persona, date, ticker, action, quantity, price FROM transaction_log WHERE date >= '2026-07-17'")
    print(df.to_string())
except Exception as e:
    print("Err1:", e)
    
try:
    print("--- CAPITAL LEDGERS ---")
    df2 = execute_query("SELECT persona, date, total_equity, cash_balance FROM capital_ledgers ORDER BY date DESC LIMIT 20")
    print(df2.to_string())
except Exception as e:
    print("Err2:", e)
os._exit(0)
"""
stdin, stdout, stderr = ssh.exec_command(f'cd /opt/antigravity && source venv/bin/activate && python -c "{script}"')
print(stdout.read().decode("utf-8"))
ssh.close()
