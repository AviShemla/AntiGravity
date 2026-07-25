import requests
import paramiko
import pandas as pd
import io

print("1. Testing Vultr API...")
try:
    r = requests.get("http://66.42.118.26/api/dashboard_data/ETF_BallsForBrains")
    print("API Response:", r.status_code)
    if r.status_code == 200:
        data = r.json()
        print("Latest Dates in API for ETF_BallsForBrains:", data['dates'][-3:])
        print("Latest Equity in API:", data['total_equity'][-3:])
except Exception as e:
    print("API Error:", e)

print("\n2. Checking Vultr CSV via SSH...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")
    stdin, stdout, stderr = ssh.exec_command("tail -n 5 /opt/antigravity/financial_data/Prod_vs_Shadow_Results_MASTER.csv")
    print("Vultr CSV Tail:")
    print(stdout.read().decode())
    ssh.close()
except Exception as e:
    print("SSH Error:", e)
