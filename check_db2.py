import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", username="root", password="M,w5_=k@eHA!ecEK")

cmd = '''cd /opt/antigravity && ./venv/bin/python3 -c "
import database_manager as dbm
df = dbm.get_ledger('BallsForBrains')
print(df.tail(4)[['Date', 'Total_Equity']].to_string())
"'''
stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode())
print(stderr.read().decode())
ssh.close()
