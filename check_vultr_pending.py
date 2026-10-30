import paramiko
import json

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    ssh.connect('66.42.118.26', port=22, username='root', password=__import__("os").environ["VULTR_ROOT_PASSWORD"])
    stdin, stdout, stderr = ssh.exec_command('cat /opt/antigravity/financial_data/Pending_Orders.json')
    data = json.loads(stdout.read().decode('utf-8'))
    print({k: v['Date'] for k,v in data.items()})
except Exception as e:
    print(f"Error: {e}")
finally:
    ssh.close()
