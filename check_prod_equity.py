import sys
sys.path.append('C:\\Users\\AviShemla\\AntiGravity')
import database_manager
df = database_manager.execute_query("SELECT date, total_equity FROM capital_ledgers WHERE persona='BallsForBrains' ORDER BY date DESC LIMIT 3")
print(df)
