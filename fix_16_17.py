
import os
import pandas as pd
from database_manager import execute_query

csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'Prod_vs_Shadow_Results_MASTER.csv')

if os.path.exists(csv_path):
    df = pd.read_csv(csv_path)
    
    if not any(df['Date'].astype(str).str.contains('2026-07-16')):
        res = execute_query('SELECT total_equity FROM capital_ledgers WHERE persona=''BallsForBrains'' AND date LIKE ''2026-07-16%''')
        if not res.empty:
            p_eq = float(res['total_equity'].iloc[-1])
            row = {'Date': '2026-07-16', 'Prod': p_eq, 'Transformer': 10611.14, 'V1_Classic': 10922.98, 'LSTM_Shadow': 10678.94}
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            
    if not any(df['Date'].astype(str).str.contains('2026-07-17')):
        res = execute_query('SELECT total_equity FROM capital_ledgers WHERE persona=''BallsForBrains'' AND date LIKE ''2026-07-17%''')
        if not res.empty:
            p_eq = float(res['total_equity'].iloc[-1])
            row = {'Date': '2026-07-17', 'Prod': p_eq, 'Transformer': 10611.14, 'V1_Classic': 10922.98, 'LSTM_Shadow': 10678.94}
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)

    df = df.sort_values('Date')
    df.to_csv(csv_path, index=False)
    print('Done!')

