import sqlite3
import json

conn = sqlite3.connect('antigravity.db')
c = conn.cursor()

# We need to recalculate the exact cash and equity for BFB and Dynamic for June 25 and June 26

def patch_persona(persona, cash_24, mcd_sold):
    # Fix June 25
    c.execute("SELECT holdings_json FROM capital_ledgers WHERE persona=? AND date='2026-06-25'", (persona,))
    row_25 = c.fetchone()
    if row_25:
        holdings = json.loads(row_25[0])
        holdings_value = sum(h['dollars'] for h in holdings.values())
        
        # Cash on 25 = Cash on 24 + MCD sold amount
        new_cash_25 = cash_24 + mcd_sold
        new_equity_25 = new_cash_25 + holdings_value
        
        c.execute("""
            UPDATE capital_ledgers 
            SET cash=?, total_equity=? 
            WHERE persona=? AND date='2026-06-25'
        """, (round(new_cash_25, 2), round(new_equity_25, 2), persona))
        print(f"Patched {persona} for 2026-06-25: Cash={new_cash_25:.2f}, Equity={new_equity_25:.2f}")

    # Fix June 26 by duplicating June 25 (since there were no trades executed on June 26)
    # This also fixes the "missing a day" issue on Olympic dashboard
    c.execute("SELECT * FROM capital_ledgers WHERE persona=? AND date='2026-06-25'", (persona,))
    fixed_row = list(c.fetchone())
    fixed_row[2] = '2026-06-26' # update date to June 26
    
    # Check if June 26 already exists
    c.execute("SELECT 1 FROM capital_ledgers WHERE persona=? AND date='2026-06-26'", (persona,))
    if c.fetchone():
        c.execute("""
            UPDATE capital_ledgers 
            SET cash=?, total_equity=?, holdings_json=?, daily_pnl_json=?, intraday_status=?
            WHERE persona=? AND date='2026-06-26'
        """, (fixed_row[3], fixed_row[4], fixed_row[5], fixed_row[6], fixed_row[7], persona))
    else:
        c.execute("""
            INSERT INTO capital_ledgers 
            (persona, date, cash, total_equity, holdings_json, daily_pnl_json, intraday_status, engine_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (fixed_row[1], fixed_row[2], fixed_row[3], fixed_row[4], fixed_row[5], fixed_row[6], fixed_row[7], fixed_row[8]))
    print(f"Patched {persona} for 2026-06-26.")

# BallsForBrains: Cash on June 24 was 7177.93. MCD was sold for ~1370.35.
patch_persona('BallsForBrains', 7177.93, 1370.35)

# Dynamic: Cash on June 24 was 9129.83. No MCD was sold.
patch_persona('Dynamic', 9129.83, 0.0)

# Neutral: Cash on June 24 was 9128.47. It hit TP/SL on NEE on June 25.
# Wait, Neutral hit TP/SL on NEE, so it should have received the NEE cash.
# Let's see Neutral June 24 holdings:
c.execute("SELECT holdings_json FROM capital_ledgers WHERE persona='Neutral' AND date='2026-06-24'")
row = c.fetchone()
if row:
    holdings = json.loads(row[0])
    nee_value = sum(h['dollars'] for h in holdings.values())
    new_cash_25 = 9128.47 + nee_value
    c.execute("UPDATE capital_ledgers SET cash=?, total_equity=? WHERE persona='Neutral' AND date='2026-06-25'", (round(new_cash_25, 2), round(new_cash_25, 2)))
    print(f"Patched Neutral for 2026-06-25: Cash={new_cash_25:.2f}")
    
    # Add June 26 for Neutral
    c.execute("SELECT * FROM capital_ledgers WHERE persona='Neutral' AND date='2026-06-25'")
    fixed_row = list(c.fetchone())
    fixed_row[2] = '2026-06-26'
    c.execute("""
        INSERT INTO capital_ledgers 
        (persona, date, cash, total_equity, holdings_json, daily_pnl_json, intraday_status, engine_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (fixed_row[1], fixed_row[2], fixed_row[3], fixed_row[4], fixed_row[5], fixed_row[6], fixed_row[7], fixed_row[8]))
    print("Patched Neutral for 2026-06-26.")

# Conservative: June 26 missing
c.execute("SELECT * FROM capital_ledgers WHERE persona='Conservative' AND date='2026-06-25'")
fixed_row = list(c.fetchone())
if fixed_row:
    fixed_row[2] = '2026-06-26'
    c.execute("""
        INSERT INTO capital_ledgers 
        (persona, date, cash, total_equity, holdings_json, daily_pnl_json, intraday_status, engine_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (fixed_row[1], fixed_row[2], fixed_row[3], fixed_row[4], fixed_row[5], fixed_row[6], fixed_row[7], fixed_row[8]))
    print("Patched Conservative for 2026-06-26.")

conn.commit()
conn.close()
