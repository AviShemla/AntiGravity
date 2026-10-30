import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    ssh.connect('66.42.118.26', port=22, username='root', password=__import__("os").environ["VULTR_ROOT_PASSWORD"])
    stdin, stdout, stderr = ssh.exec_command('ls -lat /opt/antigravity/*.log | head -n 15')
    print("LATEST LOGS:", stdout.read().decode('utf-8'))
except Exception as e:
    print(f"Error: {e}")
finally:
    ssh.close()
