import os

import pandas as pd
import database_manager
csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'Prod_vs_Shadow_Results_MASTER.csv')

df = pd.read_csv(csv_path)
last_date = df['Date'].max()
print(f'Last date in CSV: {last_date}')

dates_to_add = ['2026-07-16', '2026-07-17']

for d in dates_to_add:
    if d in df['Date'].values:
        continue
    
    prod = database_manager.execute_query(f"SELECT total_equity FROM capital_ledgers WHERE persona='BallsForBrains' AND date LIKE '{d}%' LIMIT 1")
    trans = database_manager.execute_query(f"SELECT total_equity FROM capital_ledgers WHERE persona='Dynamic' AND date LIKE '{d}%' LIMIT 1")
    v1 = database_manager.execute_query(f"SELECT total_equity FROM capital_ledgers WHERE persona='Conservative' AND date LIKE '{d}%' LIMIT 1")
    lstm = database_manager.execute_query(f"SELECT total_equity FROM capital_ledgers WHERE persona='Neutral' AND date LIKE '{d}%' LIMIT 1")
    
    if not prod.empty and not trans.empty and not v1.empty and not lstm.empty:
        new_row = {
            'Date': d,
            'Prod': prod.iloc[0]['total_equity'],
            'Shadow_Transformer': trans.iloc[0]['total_equity'],
            'Sandbox_V1': v1.iloc[0]['total_equity'],
            'Shadow_LSTM': lstm.iloc[0]['total_equity']
        }
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        print(f'Added {d}')

df.to_csv(csv_path, index=False)
print('Done!')

