import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password=__import__("os").environ["VULTR_ROOT_PASSWORD"])
stdin, stdout, stderr = ssh.exec_command("tail -n 30 /opt/antigravity/master_watchdog.log")
print(stdout.read().decode('utf-8'))
ssh.close()
