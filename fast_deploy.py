import paramiko
import os
import time

def deploy():
    print("Starting fast deploy...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")
    
    sftp = ssh.open_sftp()
    
    files_to_upload = [
        ("server.py", "/opt/antigravity/server.py"),
        ("frontend/index.html", "/opt/antigravity/frontend/index.html"),
        ("frontend/Architecture_Map.html", "/opt/antigravity/frontend/Architecture_Map.html"),
        ("frontend/app.js", "/opt/antigravity/frontend/app.js")
    ]
    
    # Check if CSVs exist and upload them
    csv_files = [
        ("financial_data/Prod_vs_Shadow_Results_MASTER.csv", "/opt/antigravity/financial_data/Prod_vs_Shadow_Results_MASTER.csv"),
        ("financial_data/Olympic_Shootout_Results_MASTER.csv", "/opt/antigravity/financial_data/Olympic_Shootout_Results_MASTER.csv")
    ]
    for local_path, remote_path in csv_files:
        if os.path.exists(local_path):
            files_to_upload.append((local_path, remote_path))
    
    ssh.exec_command("mkdir -p /opt/antigravity/financial_data")
    
    for local_path, remote_path in files_to_upload:
        print(f"Uploading {local_path} to {remote_path}...")
        sftp.put(local_path, remote_path)
        
    sftp.close()
    
    print("Restarting Uvicorn on VPS...")
    ssh.exec_command("pkill -9 -f uvicorn")
    time.sleep(2)
    ssh.exec_command("cd /opt/antigravity && source venv/bin/activate && nohup uvicorn server:app --host 0.0.0.0 --port 80 > /dev/null 2>&1 &")
    
    print("Deployment and restart complete!")
    ssh.close()

if __name__ == "__main__":
    deploy()
