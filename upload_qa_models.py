import paramiko

print("Uploading qa_models.py to Vultr...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    ssh.connect('66.42.118.26', port=22, username='root', password='M,w5_=k@eHA!ecEK')
    sftp = ssh.open_sftp()
    
    FILES_TO_UPLOAD = [
        "lock_buster.py",
        "database_manager.py",
        "export_bayesian_scorecard_formatted.py",
        "prod_vs_shadow_tracker.py",
        "run_backtests.py"
    ]
    for file in FILES_TO_UPLOAD:
        local_file = f"C:/Users/AviShemla/AntiGravity/{file}"
        remote_file = f"/opt/antigravity/{file}"
        sftp.put(local_file, remote_file)
        print(f"Uploaded {file}")
    sftp.close()
    
    print("Restarting processes on Vultr...")
    ssh.exec_command('systemctl restart ag-uvicorn; systemctl restart ag-sniper')
    
    print("Upload complete!")
except Exception as e:
    print(f"Error: {e}")
finally:
    ssh.close()
