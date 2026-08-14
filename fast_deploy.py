import paramiko
import os

def deploy():
    print("Pushing UI and Server Patches to Vultr...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")
    
    sftp = ssh.open_sftp()
    
    files_to_upload = [
        ("server.py", "/opt/antigravity/server.py"),
        ("database_manager.py", "/opt/antigravity/database_manager.py"),
        ("data_loader.py", "/opt/antigravity/data_loader.py"),
        ("export_bayesian_scorecard_formatted.py", "/opt/antigravity/export_bayesian_scorecard_formatted.py"),
        ("laptop_catchup_controller.py", "/opt/antigravity/laptop_catchup_controller.py"),
        ("frontend/app.js", "/opt/antigravity/frontend/app.js"),
        ("frontend/index.html", "/opt/antigravity/frontend/index.html"),
        ("frontend/style_3d.css", "/opt/antigravity/frontend/style_3d.css"),
        ("frontend/Architecture_Map.html", "/opt/antigravity/frontend/Architecture_Map.html"),
        ("clean_ghosts.py", "/opt/antigravity/clean_ghosts.py"),
        ("check_progress.py", "/opt/antigravity/check_progress.py"),
        ("financial_data/Prod_vs_Shadow_Results_MASTER.csv", "/opt/antigravity/financial_data/Prod_vs_Shadow_Results_MASTER.csv"),
        ("financial_data/Olympic_Shootout_Results_MASTER.csv", "/opt/antigravity/financial_data/Olympic_Shootout_Results_MASTER.csv"),
        ("financial_data/Top5_Bayesian_Scorecard_Formatted.xlsx", "/opt/antigravity/financial_data/Top5_Bayesian_Scorecard_Formatted.xlsx"),
        ("financial_data/All_ETFs_Scorecard.xlsx", "/opt/antigravity/financial_data/All_ETFs_Scorecard.xlsx"),
        ("qa_financial_audit.py", "/opt/antigravity/qa_financial_audit.py")
    ]
    
    for local_path, remote_path in files_to_upload:
        if os.path.exists(local_path):
            print(f"Uploading {local_path} to {remote_path}...")
            sftp.put(local_path, remote_path)
        else:
            print(f"ERROR: Cannot find {local_path} locally!")
            
    sftp.close()
    
    print("Killing old Uvicorn instances on Vultr...")
    ssh.exec_command("pkill -9 -f uvicorn")
    
    print("Restarting Uvicorn server...")
    ssh.exec_command("cd /opt/antigravity && nohup ./venv/bin/python3 -m uvicorn server:app --host 0.0.0.0 --port 80 > /dev/null 2>&1 &")
    
    print("Successfully pushed to Vultr and restarted server.")
    ssh.close()

if __name__ == "__main__":
    deploy()
