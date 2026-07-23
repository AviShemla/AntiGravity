import paramiko
import os
import time

def deploy():
    print("Starting Vultr Prefect Patch...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")
    
    sftp = ssh.open_sftp()
    
    files_to_upload = [
        ("prefect_pipeline.py", "/opt/antigravity/prefect_pipeline.py"),
        ("clean_ghosts.py", "/opt/antigravity/clean_ghosts.py"),
        ("master_watchdog.py", "/opt/antigravity/master_watchdog.py")
    ]
    
    for local_path, remote_path in files_to_upload:
        if os.path.exists(local_path):
            print(f"Uploading {local_path} to {remote_path}...")
            sftp.put(local_path, remote_path)
        
    sftp.close()
    
    print("Hunting down old watchdogs on Vultr...")
    ssh.exec_command("pkill -9 -f master_watchdog.py")
    
    print("Restarting Prefect Server Pipeline...")
    ssh.exec_command("pkill -9 -f prefect_pipeline.py")
    time.sleep(2)
    # Restart the prefect service in the background
    ssh.exec_command("cd /opt/antigravity && nohup python3 prefect_pipeline.py serve > /opt/antigravity/prefect_serve.log 2>&1 &")
    
    print("Vultr Deployment complete!")
    ssh.close()

if __name__ == "__main__":
    deploy()
