import sys
sys.path.append(r'C:\Users\AviShemla\AntiGravity')
import database_manager
import pandas as pd
import sqlite3
import json

persona = "Conservative"
conn = database_manager.get_connection()
cursor = conn.cursor()

# Get April 28 row to see EXACTLY what was passed to April 29
r28 = cursor.execute("SELECT * FROM capital_ledgers WHERE persona=? AND date=?", (persona, "2026-04-28")).fetchone()
print(f"April 28 row: {r28}")

conn.close()

# Now simulate virtual_broker for April 29 using the exact code
import virtual_broker

# Let's see what virtual broker outputs for 2026-04-29
import io
from contextlib import redirect_stdout

f = io.StringIO()
with redirect_stdout(f):
    try:
        # We need to simulate the loop in virtual_broker.py
        pass
    except Exception as e:
        print(f"Error: {e}")

# Actually let's just run it!
import subprocess
subprocess.run([sys.executable, "C:\\Users\\AviShemla\\AntiGravity\\virtual_broker.py", "--target-date", "2026-04-29"])

