import database_manager
import json

df_held = database_manager.execute_query("SELECT holdings_json FROM capital_ledgers WHERE persona LIKE 'ETF_%'")
print("Rows returned:", len(df_held))
if not df_held.empty:
    print(df_held.iloc[-1]['holdings_json'])
    
    TARGET_ETFS = []
    for idx, row in df_held.iterrows():
        try:
            val = row['holdings_json']
            holdings = json.loads(val) if isinstance(val, str) else val
            for t in holdings.keys():
                if t != 'Cash' and t not in TARGET_ETFS:
                    TARGET_ETFS.append(t)
        except Exception as e:
            print("Error parsing row:", e)
    print("Found TARGET_ETFS:", TARGET_ETFS)
