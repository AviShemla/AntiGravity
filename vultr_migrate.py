import paramiko
import os
import time

def run():
    print("Connecting to Vultr...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")
    
    def exec_cmd(cmd):
        print(f"Executing: {cmd}")
        stdin, stdout, stderr = ssh.exec_command(cmd)
        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8')
        err = stderr.read().decode('utf-8')
        if exit_status != 0:
            print(f"ERROR: {err}")
        return out, exit_status

    print("1. Creating systemd service for ag-uvicorn...")
    uvicorn_service = """[Unit]
Description=AntiGravity Uvicorn Web Server
After=network.target

[Service]
User=root
WorkingDirectory=/opt/antigravity
Environment="PATH=/opt/antigravity/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/opt/antigravity/venv/bin/uvicorn server:app --host 0.0.0.0 --port 80
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""
    sftp = ssh.open_sftp()
    with sftp.file('/etc/systemd/system/ag-uvicorn.service', 'w') as f:
        f.write(uvicorn_service)

    print("2. Creating systemd service for ag-sniper...")
    sniper_service = """[Unit]
Description=AntiGravity Intraday Sniper
After=network.target

[Service]
User=root
WorkingDirectory=/opt/antigravity
Environment="PATH=/opt/antigravity/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/opt/antigravity/venv/bin/python intraday_tracker.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    with sftp.file('/etc/systemd/system/ag-sniper.service', 'w') as f:
        f.write(sniper_service)

    print("3. Creating systemd service for ag-vix...")
    vix_service = """[Unit]
Description=AntiGravity VIX Watchdog
After=network.target

[Service]
User=root
WorkingDirectory=/opt/antigravity
Environment="PATH=/opt/antigravity/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/opt/antigravity/venv/bin/python vix_monitor.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    with sftp.file('/etc/systemd/system/ag-vix.service', 'w') as f:
        f.write(vix_service)

    sftp.close()

    print("Reloading systemd daemon...")
    exec_cmd("systemctl daemon-reload")
    
    print("Installing Prefect on Vultr...")
    exec_cmd("/opt/antigravity/venv/bin/pip install prefect")

    print("Killing existing uvicorn and python processes on VPS...")
    exec_cmd("pkill -9 -f uvicorn")
    exec_cmd("pkill -9 -f intraday_tracker")
    exec_cmd("pkill -9 -f vix_monitor")

    print("Starting systemd services...")
    exec_cmd("systemctl enable ag-uvicorn")
    exec_cmd("systemctl start ag-uvicorn")
    exec_cmd("systemctl enable ag-sniper")
    exec_cmd("systemctl start ag-sniper")
    exec_cmd("systemctl enable ag-vix")
    exec_cmd("systemctl start ag-vix")

    ssh.close()
    print("Vultr Systemd Migration Complete.")

if __name__ == "__main__":
    run()
