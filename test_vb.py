import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', port=22, username='root', password=__import__("os").environ["VULTR_ROOT_PASSWORD"])
i, o, e = ssh.exec_command('cd /opt/antigravity && /opt/antigravity/venv/bin/python -u -c "import sys; sys.argv=[\'virtual_broker.py\', \'SINGLE\', \'2026-07-24\']; import virtual_broker; virtual_broker.run_virtual_broker()"')
print("OUT:", o.read().decode('utf-8'))
print("ERR:", e.read().decode('utf-8'))
ssh.close()
