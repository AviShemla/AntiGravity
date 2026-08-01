import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', port=22, username='root', password='M,w5_=k@eHA!ecEK')

print("MASTER_LEDGER.DB:")
stdin, stdout, stderr = ssh.exec_command('python3 -c "import sqlite3; conn = sqlite3.connect(\'/opt/antigravity/master_ledger.db\'); cur = conn.cursor(); cur.execute(\\"SELECT persona, date, intraday_status FROM capital_ledgers WHERE date >= \'2026-07-31\'\\"); print(cur.fetchall())"')
print(stdout.read().decode())
err = stderr.read().decode()
if err: print("Error:", err)

print("CAPITAL_LEDGERS.DB:")
stdin, stdout, stderr = ssh.exec_command('python3 -c "import sqlite3; conn = sqlite3.connect(\'/opt/antigravity/capital_ledgers.db\'); cur = conn.cursor(); cur.execute(\\"SELECT persona, date, intraday_status FROM capital_ledgers WHERE date >= \'2026-07-31\'\\"); print(cur.fetchall())"')
print(stdout.read().decode())
err = stderr.read().decode()
if err: print("Error:", err)
