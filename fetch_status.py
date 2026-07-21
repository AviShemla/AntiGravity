import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

script = """
import os
import sys

def run():
    try:
        sys.path.append("/opt/antigravity")
        os.chdir("/opt/antigravity")
        from database_manager import execute_query
        
        print("=== PENDING ORDERS ===")
        df_pending = execute_query("SELECT persona, ticker, action, quantity, target_price FROM pending_orders")
        print(df_pending.to_string() if not df_pending.empty else "No Pending Orders")
        
        print("\n=== INTRADAY TRACKER ===")
        # Usually Intraday Sniper logs or a specific intraday table exist. Let's check ledger.
        df_ledger = execute_query("SELECT persona, date, total_equity, cash_balance FROM capital_ledgers ORDER BY date DESC LIMIT 10")
        print(df_ledger.to_string() if not df_ledger.empty else "No Ledger Data")
        
    except Exception as e:
        print("DB Error:", e)
    finally:
        os._exit(0)

if __name__ == '__main__':
    run()
"""

stdin, stdout, stderr = ssh.exec_command(f'cd /opt/antigravity && source venv/bin/activate && python -c "{script}"')
out = stdout.read().decode("utf-8")
err = stderr.read().decode("utf-8")
print(out)
if err: print("ERR:", err)
ssh.close()
