import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    ssh.connect('66.42.118.26', port=22, username='root', password=__import__("os").environ["VULTR_ROOT_PASSWORD"])
    # the tracker usually prints to stdout/stderr or a log file.
    # Prefect captures logs. But wait, I can just look at the python script I wrote earlier
    stdin, stdout, stderr = ssh.exec_command('ps aux | grep intraday_tracker')
    print("PS:", stdout.read().decode('utf-8'))
    
    # Try finding any log file with intraday
    stdin, stdout, stderr = ssh.exec_command('ls -la /opt/antigravity/*.log')
    print("LOGS:", stdout.read().decode('utf-8'))
except Exception as e:
    print(f"Error: {e}")
finally:
    ssh.close()
