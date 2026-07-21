import paramiko
import os

with open(r"C:\Users\AviShemla\.ssh\id_rsa.pub", "r") as f:
    pub_key = f.read().strip()

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

stdin, stdout, stderr = ssh.exec_command(f'mkdir -p ~/.ssh && echo "{pub_key}" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys')
out = stdout.read().decode()
err = stderr.read().decode()
ssh.close()
print("Key Injected Successfully!")
