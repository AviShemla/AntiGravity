import pandas as pd
from database_manager import execute_query

def check():
    df = execute_query("SELECT * FROM capital_ledgers WHERE persona = 'ETF_Balls For Brain' ORDER BY date DESC LIMIT 5")
    if not df.empty:
        print("Broken Persona Rows (ETF_Balls For Brain):")
        print(df[['date', 'total_equity', 'cash']].to_string())
    else:
        print("No rows found for ETF_Balls For Brain")

    df2 = execute_query("SELECT * FROM capital_ledgers WHERE persona = 'ETF_BallsForBrains' ORDER BY date DESC LIMIT 5")
    if not df2.empty:
        print("\nCorrect Persona Rows (ETF_BallsForBrains):")
        print(df2[['date', 'total_equity', 'cash']].to_string())
    else:
        print("No rows found for ETF_BallsForBrains")

check()
