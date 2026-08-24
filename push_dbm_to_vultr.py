import paramiko
import os

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    ssh.connect('66.42.118.26', port=22, username='root', password=__import__("os").environ["VULTR_ROOT_PASSWORD"])
    sftp = ssh.open_sftp()
    
    local_path = "C:/Users/AviShemla/AntiGravity/database_manager.py"
    remote_path = "/opt/antigravity/database_manager.py"
    
    sftp.put(local_path, remote_path)
    print("Successfully pushed fixed database_manager.py to Vultr!")
    sftp.close()
except Exception as e:
    print(f"Error: {e}")
finally:
    ssh.close()
