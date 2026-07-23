import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", username="root", password="M,w5_=k@eHA!ecEK")

cmd = '''cd /opt/antigravity/financial_data &&
echo "--- Prod vs Shadow ---"
tail -n 2 Prod_vs_Shadow_Results_MASTER.csv
echo "--- Olympic ---"
tail -n 2 Olympic_Shootout_Results_MASTER.csv
'''
stdin, stdout, stderr = ssh.exec_command(cmd)
print('STDOUT:\n', stdout.read().decode())
print('STDERR:\n', stderr.read().decode())
ssh.close()
