import sys
sys.path.append('C:/Users/AviShemla/AntiGravity')
import database_manager
print(database_manager.get_ledger('BallsForBrains').tail(5)[['Date', 'Total_Equity']])
