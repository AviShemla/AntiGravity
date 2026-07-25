import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")
    sftp = ssh.open_sftp()
    
    files = [
        ("C:/Users/AviShemla/AntiGravity/financial_data/Prod_vs_Shadow_Results_MASTER.csv", "/opt/antigravity/financial_data/Prod_vs_Shadow_Results_MASTER.csv"),
        ("C:/Users/AviShemla/AntiGravity/financial_data/Olympic_Shootout_Results_MASTER.csv", "/opt/antigravity/financial_data/Olympic_Shootout_Results_MASTER.csv")
    ]
    
    for local_csv, remote_csv in files:
        print(f"Uploading {local_csv} to Vultr...")
        try:
            sftp.put(local_csv, remote_csv)
        except Exception as ex:
            print(f"Failed to upload {local_csv}: {ex}")
            
    sftp.close()
    
    print("Restarting Uvicorn to flush cache...")
    ssh.exec_command("pkill -9 -f uvicorn")
    ssh.exec_command("cd /opt/antigravity && nohup ./venv/bin/python3 -m uvicorn server:app --host 0.0.0.0 --port 80 > /dev/null 2>&1 &")
    
    print("Success.")
except Exception as e:
    print(f"Error: {e}")
finally:
    ssh.close()
