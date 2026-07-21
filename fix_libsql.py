import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

script = """
cd /opt/antigravity
source venv/bin/activate
pip install libsql-client
python prefect_pipeline.py qa
"""
stdin, stdout, stderr = ssh.exec_command(script)
exit_status = stdout.channel.recv_exit_status()
print(stdout.read().decode('utf-8', errors='ignore'))
ssh.close()
