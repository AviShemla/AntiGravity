
import database_manager
df_single = database_manager.execute_query('SELECT persona, total_equity FROM capital_ledgers WHERE persona=''Conservative'' ORDER BY date DESC LIMIT 1')
df_etf = database_manager.execute_query('SELECT persona, total_equity FROM capital_ledgers WHERE persona=''ETF_Conservative'' ORDER BY date DESC LIMIT 1')
print('Single:', df_single.iloc[0]['total_equity'] if not df_single.empty else 'none')
print('ETF:', df_etf.iloc[0]['total_equity'] if not df_etf.empty else 'none')

