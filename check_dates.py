import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", username="root", password="M,w5_=k@eHA!ecEK")

cmd = '''cd /opt/antigravity && ./venv/bin/python3 -c "
import database_manager as dbm
df = dbm.get_ledger('BallsForBrains')
print(df['Date'].tail(5).tolist())
"'''
stdin, stdout, stderr = ssh.exec_command(cmd)
print('STDOUT:', stdout.read().decode())
print('STDERR:', stderr.read().decode())
ssh.close()
