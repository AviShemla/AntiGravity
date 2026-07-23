import paramiko

def verify():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")
    
    print("Checking app.js for dtick:")
    stdin, stdout, stderr = ssh.exec_command("cat /opt/antigravity/frontend/app.js | grep dtick")
    print(stdout.read().decode())
    
    print("Checking server.py for reindex:")
    stdin, stdout, stderr = ssh.exec_command("cat /opt/antigravity/server.py | grep reindex")
    print(stdout.read().decode())
    
    print("Checking running Uvicorn process:")
    stdin, stdout, stderr = ssh.exec_command("ps aux | grep uvicorn")
    print(stdout.read().decode())
    
    ssh.close()

if __name__ == "__main__":
    verify()
