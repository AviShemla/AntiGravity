import sqlite3
import json

try:
    conn = sqlite3.connect('antigravity.db')
    c = conn.cursor()
    # Need to join with itself to get the rows with the max date for each persona
    c.execute("""
        SELECT a.persona, a.date, a.cash, a.total_equity, a.holdings_json 
        FROM capital_ledgers a
        INNER JOIN (
            SELECT persona, MAX(date) as max_date 
            FROM capital_ledgers 
            GROUP BY persona
        ) b ON a.persona = b.persona AND a.date = b.max_date
        ORDER BY a.persona;
    """)
    for r in c.fetchall():
        try:
            h = json.loads(r[4])
        except:
            h = r[4]
        print(f"[{r[0]}] Date: {r[1]} | Equity: ${r[3]:.2f} | Cash: ${r[2]:.2f}")
        print(f"Holdings: {h}\n")
except Exception as e:
    print("Error:", e)
