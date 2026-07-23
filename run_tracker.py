import paramiko

def run():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('66.42.118.26', username='root', password='M,w5_=k@eHA!ecEK')
    
    print("Running prod_vs_shadow_tracker.py on Vultr...")
    cmd = "cd /opt/antigravity && ./venv/bin/python3 prod_vs_shadow_tracker.py"
    stdin, stdout, stderr = ssh.exec_command(cmd)
    
    out = stdout.read().decode()
    err = stderr.read().decode()
    print("STDOUT:", out)
    print("STDERR:", err)
    ssh.close()

if __name__ == "__main__":
    run()
