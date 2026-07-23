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
        ("frontend/app.js", "/opt/antigravity/frontend/app.js")
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
