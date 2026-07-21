import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

script = """
import sys, os
sys.path.append("/opt/antigravity")
import laptop_catchup_controller
import database_manager

# Monkey patch the logic bug so it is forced to process today
laptop_catchup_controller.get_missed_dates = lambda x: ['2026-07-20']

# Force the execution
print("=== FORCE EXECUTING MASTER PIPELINE FOR 2026-07-20 ===")
laptop_catchup_controller.catchup_master_pipeline()
"""

stdin, stdout, stderr = ssh.exec_command(f'cd /opt/antigravity && source venv/bin/activate && nohup python -u -c "{script}" > force_stock.log 2>&1 &')
ssh.close()
