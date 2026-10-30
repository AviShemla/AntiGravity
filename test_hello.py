import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', port=22, username='root', password=__import__("os").environ["VULTR_ROOT_PASSWORD"])
i, o, e = ssh.exec_command('/opt/antigravity/venv/bin/python -c "print(\'hello\')"')
print(o.read().decode('utf-8'))
print(e.read().decode('utf-8'))
ssh.close()
