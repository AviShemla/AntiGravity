import paramiko
import os
import time

def deploy():
    print("Pushing Anti-Deadlock Patch to Vultr...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")
    
    sftp = ssh.open_sftp()
    
    local_path = "vix_monitor.py"
    remote_path = "/opt/antigravity/vix_monitor.py"
    
    if os.path.exists(local_path):
        print(f"Uploading {local_path} to {remote_path}...")
        sftp.put(local_path, remote_path)
        
    sftp.close()
    
    print("Killing old VIX monitor...")
    ssh.exec_command("pkill -9 -f vix_monitor.py")
    
    print("VIX Patch Deployed. Prefect will automatically reboot the VIX monitor within 15 minutes.")
    ssh.close()

if __name__ == "__main__":
    deploy()
