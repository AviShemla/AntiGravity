import paramiko

def peek_vultr():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")
    
    # We will upload a tiny read-only peek script to Vultr and run it
    sftp = ssh.open_sftp()
    
    remote_script = """import sys, os, json, time
sys.path.append('/opt/antigravity')
import database_manager
from intraday_tracker import get_yesterday_metrics, get_live_metrics, get_vix_score

print("=== LIVE VULTR SNIPER RADAR ===")
vix = get_vix_score()
print(f"Live VIX Score: {vix}\\n")

df = database_manager.execute_query("SELECT persona, target_holdings_json FROM pending_orders LIMIT 1")
if df.empty:
    print("No pending orders found.")
    sys.exit(0)
    
row = df.iloc[0]
target = json.loads(row['target_holdings_json']) if isinstance(row['target_holdings_json'], str) else row['target_holdings_json']
tickers = list(target.keys())[:3]

for ticker in tickers:
    print(f"Stalking: {ticker} (Persona: {row['persona']})")
    yest_close, yest_vwap = get_yesterday_metrics(ticker)
    live_price, live_volume = get_live_metrics(ticker)
    
    if not yest_close or not live_price:
        print("  -> Waiting on Yahoo Finance data...")
        continue
        
    dynamic_vwap_threshold = yest_vwap * 1.005
    
    print(f"  -> Yesterday Close: ${yest_close:.2f} | Yesterday VWAP: ${yest_vwap:.2f}")
    print(f"  -> Target Breakout: ${dynamic_vwap_threshold:.2f} | Live Ask Price: ${live_price:.2f}")
    
    if (live_price > yest_close) and (live_price > dynamic_vwap_threshold):
        print("  -> STATUS: MOMENTUM PASSED. Awaiting Volume Confirmation.")
    else:
        print("  -> STATUS: MOMENTUM FAILED. Holding fire.")
    print("-" * 50)
"""
    
    with sftp.file('/tmp/peek_script.py', 'w') as f:
        f.write(remote_script)
        
    sftp.close()
    
    print("Executing peek script directly on Vultr...")
    stdin, stdout, stderr = ssh.exec_command("/opt/antigravity/venv/bin/python /tmp/peek_script.py")
    
    out = stdout.read().decode()
    err = stderr.read().decode()
    
    if out: print(out)
    if err: print("ERRORS:", err)
    
    ssh.close()

if __name__ == "__main__":
    peek_vultr()
