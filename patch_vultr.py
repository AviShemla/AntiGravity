import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', port=22, username='root', password='M,w5_=k@eHA!ecEK')

cmd = r"sed -i 's/n_val = sl1.stop - 1 - sl2 \* sl1.step/n_val = int(sl1.stop) - 1 - int(sl2) * int(sl1.step)/g' /opt/antigravity/venv/lib/python3.14/site-packages/pytensor/tensor/rewriting/subtensor.py"
i, o, e = ssh.exec_command(cmd)
print("OUT:", o.read().decode('utf-8'))
print("ERR:", e.read().decode('utf-8'))

cmd2 = "nohup /opt/antigravity/venv/bin/python /opt/antigravity/prefect_pipeline.py > /opt/antigravity/manual_nightly.log 2>&1 &"
i, o, e = ssh.exec_command(cmd2)
print("Pipeline Restarted.")
ssh.close()
