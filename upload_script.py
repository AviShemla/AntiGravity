import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', port=22, username='root', password='M,w5_=k@eHA!ecEK')

sftp = ssh.open_sftp()
sftp.put('C:\\Users\\AviShemla\\AntiGravity\\daily_pipeline.py', '/opt/antigravity/daily_pipeline.py')
sftp.put('C:\\Users\\AviShemla\\AntiGravity\\etf_daily_pipeline.py', '/opt/antigravity/etf_daily_pipeline.py')
sftp.put('C:\\Users\\AviShemla\\AntiGravity\\verify_launch.py', '/opt/antigravity/verify_launch.py')
sftp.put('C:\\Users\\AviShemla\\AntiGravity\\migrate_to_sqlite.py', '/opt/antigravity/migrate_to_sqlite.py')
sftp.put('C:\\Users\\AviShemla\\AntiGravity\\prod_vs_shadow_tracker.py', '/opt/antigravity/prod_vs_shadow_tracker.py')
sftp.put('C:\\Users\\AviShemla\\AntiGravity\\system_health_monitor.py', '/opt/antigravity/system_health_monitor.py')
sftp.put('C:\\Users\\AviShemla\\AntiGravity\\system_qa_auditor.py', '/opt/antigravity/system_qa_auditor.py')
sftp.close()
ssh.close()
print("Upload complete!")
