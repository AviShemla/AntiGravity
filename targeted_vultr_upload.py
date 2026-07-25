import paramiko
import os

print("Starting targeted fast upload...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    ssh.connect('66.42.118.26', port=22, username='root', password='M,w5_=k@eHA!ecEK')
    sftp = ssh.open_sftp()
    
    local_json = "C:/Users/AviShemla/AntiGravity/financial_data/Pending_Orders.json"
    remote_json = "/opt/antigravity/financial_data/Pending_Orders.json"
    print("Uploading Pending_Orders.json...")
    sftp.put(local_json, remote_json)
    
    local_db = "C:/Users/AviShemla/AntiGravity/financial_data/ag_pipeline_fallback.db"
    remote_db = "/opt/antigravity/financial_data/ag_pipeline_fallback.db"
    print("Uploading ag_pipeline_fallback.db...")
    if os.path.exists(local_db):
        sftp.put(local_db, remote_db)
    
    sftp.close()
    print("Upload complete!")
except Exception as e:
    print(f"Error: {e}")
finally:
    ssh.close()
