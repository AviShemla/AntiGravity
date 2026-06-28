import sqlite3
import json

conn = sqlite3.connect('antigravity.db')
c = conn.cursor()

# Fix ETF_Neutral
c.execute("""
    UPDATE capital_ledgers 
    SET cash = ?, total_equity = ?, holdings_json = ? 
    WHERE persona = 'ETF_Neutral' AND date = '2026-06-24'
""", (9549.70, 9986.49, '{"MSTZ": {"dollars": 436.79, "units": 38, "price": 11.49447}}'))

# Fix ETF_Dynamic
c.execute("""
    UPDATE capital_ledgers 
    SET cash = ?, total_equity = ?, holdings_json = ? 
    WHERE persona = 'ETF_Dynamic' AND date = '2026-06-24'
""", (9549.70, 10015.20, '{"MSTZ": {"dollars": 465.50, "units": 38, "price": 12.25}}'))

# Fix ETF_BallsForBrains
c.execute("""
    UPDATE capital_ledgers 
    SET cash = ?, total_equity = ?, holdings_json = ? 
    WHERE persona = 'ETF_BallsForBrains' AND date = '2026-06-24'
""", (8495.83, 10030.80, '{"IGV": {"dollars": 261.96, "units": 3, "price": 87.31999969482422}, "MTUM": {"dollars": 329.76, "units": 1, "price": 329.760009765625}, "MSTZ": {"dollars": 943.25, "units": 77, "price": 12.25}}'))

conn.commit()
conn.close()
print("Database anomalies corrected!")
