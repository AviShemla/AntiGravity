import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', port=22, username='root', password='M,w5_=k@eHA!ecEK')
i, o, e = ssh.exec_command('cd /opt/antigravity && /opt/antigravity/venv/bin/python -c "import sys; sys.argv=[\'etf_virtual_broker.py\', \'--target-date\', \'2026-07-24\']; import etf_virtual_broker; etf_virtual_broker.run_etf_virtual_broker()"')
print("OUT:", o.read().decode('utf-8'))
print("ERR:", e.read().decode('utf-8'))
ssh.close()
