import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', port=22, username='root', password='M,w5_=k@eHA!ecEK')

sftp = ssh.open_sftp()
script = '''import sys
sys.path.append("/opt/antigravity")
import laptop_catchup_controller
print("Missed Master:", laptop_catchup_controller.get_missed_dates("master_pipeline"))
print("Missed ETF:", laptop_catchup_controller.get_missed_dates("etf_pipeline"))
'''
with sftp.file('/opt/antigravity/test_missed.py', 'w') as f:
    f.write(script)

sftp.close()

i, o, e = ssh.exec_command('/opt/antigravity/venv/bin/python /opt/antigravity/test_missed.py')
print(o.read().decode('utf-8'))
print(e.read().decode('utf-8'))
ssh.close()
