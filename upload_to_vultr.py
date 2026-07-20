import paramiko
import os

files_to_upload = [
    ('frontend/index.html', '/opt/antigravity/frontend/index.html'),
    ('frontend/Architecture_Map.html', '/opt/antigravity/frontend/Architecture_Map.html'),
    ('prefect_pipeline.py', '/opt/antigravity/prefect_pipeline.py')
]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', username='root', password='M,w5_=k@eHA!ecEK')

sftp = ssh.open_sftp()
for local, remote in files_to_upload:
    try:
        sftp.put(local, remote)
        print(f'Uploaded {local} to {remote}')
    except Exception as e:
        print(f'Failed to upload {local}: {e}')

sftp.close()
ssh.close()
