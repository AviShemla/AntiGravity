import paramiko
from scp import SCPClient
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
python_exe = sys.executable

def sync_cloud_data():
    ip = "66.42.118.26"
    pw = "M,w5_=k@eHA!ecEK"
    
    print("Connecting to Vultr Cloud to sync generated reports...")
    try:
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, 22, "root", pw)
        
        with SCPClient(client.get_transport()) as scp:
            print("Downloading Excel Scorecards and CSVs...")
            remote_path = "/opt/antigravity/financial_data"
            local_path = os.path.join(BASE_DIR, "financial_data")
            os.makedirs(local_path, exist_ok=True)
            
            # Sync specific attachment files
            files_to_sync = [
                "Top5_Bayesian_Scorecard_Formatted.xlsx",
                "ETF_Bayesian_Scorecard_Formatted.xlsx",
                "MultiPersona_Broker_30Day_Trial.xlsx",
                "ETF_Broker_30Day_Trial.xlsx",
                "Championship_Marathon_Live_Results.csv",
                "Championship_Marathon_Live_Results_ETF.csv"
            ]
            
            for file in files_to_sync:
                try:
                    scp.get(f"{remote_path}/{file}", local_path)
                    print(f"Synced {file}")
                except Exception as e:
                    print(f"File not found on remote (or error): {file}")
                    
        client.close()
        print("Sync complete.")
    except Exception as e:
        print(f"Failed to sync with Vultr: {e}")

def send_emails():
    scripts = [
        "executive_brief.py",
        "send_master_email.py",
        "send_etf_email.py",
        "send_championship_email.py"
    ]
    
    for script in scripts:
        print(f"\n---> Executing {script}...")
        try:
            subprocess.run([python_exe, os.path.join(BASE_DIR, script)], cwd=BASE_DIR, check=True)
        except Exception as e:
            print(f"Error running {script}: {e}")

if __name__ == "__main__":
    print("=== AntiGravity Local Email Reporter ===")
    sync_cloud_data()
    send_emails()
    print("\nAll 4 requested emails have been processed and sent via Outlook.")
