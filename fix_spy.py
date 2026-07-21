import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")

# 1. Install lxml
ssh.exec_command("cd /opt/antigravity && source venv/bin/activate && pip install lxml")

# 2. Fix SPY.py import shadowing
script = """
import sys
with open('/opt/antigravity/SPY.py', 'r') as f:
    content = f.read()
# Remove the shadowed import json inside the grandfathering block
content = content.replace('        import json\\n        from database_manager', '        from database_manager')
with open('/opt/antigravity/SPY.py', 'w') as f:
    f.write(content)
"""
ssh.exec_command(f'python -c "{script}"')

# 3. Re-run the forceful ML pipeline execution
ssh.exec_command("cd /opt/antigravity && source venv/bin/activate && nohup python -u force_run_script.py > force_stock.log 2>&1 &")
ssh.close()
