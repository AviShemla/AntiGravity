import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")
    
    stdin, stdout, stderr = ssh.exec_command("tail -n 5 /opt/antigravity/Olympic_Shootout_Results_MASTER.csv")
    print("Vultr Root Dir:", stdout.read().decode())

    stdin, stdout, stderr = ssh.exec_command("tail -n 5 /opt/antigravity/financial_data/Olympic_Shootout_Results_MASTER.csv")
    print("Vultr Financial_Data Dir:", stdout.read().decode())
    
    ssh.close()
except Exception as e:
    print(f"Error: {e}")
