
import database_manager
df = database_manager.get_ledger('ETF_Conservative')
if not df.empty:
    print('Persona in DB for ETF_Conservative query:', df['Total_Equity'].iloc[-1])
else:
    print('Empty!')

