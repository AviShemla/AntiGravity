import pandas as pd
from database_manager import execute_query
pd.set_option('display.max_columns', None)
df = execute_query("SELECT persona, date, intraday_status FROM capital_ledgers WHERE persona='BallsForBrains'")
print(df)
