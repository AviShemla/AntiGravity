import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', port=22, username='root', password=__import__("os").environ["VULTR_ROOT_PASSWORD"])
sftp = ssh.open_sftp()
sftp.put('C:\\Users\\AviShemla\\AntiGravity\\virtual_broker.py', '/opt/antigravity/virtual_broker.py')
sftp.close()
ssh.close()
print("Uploaded!")
