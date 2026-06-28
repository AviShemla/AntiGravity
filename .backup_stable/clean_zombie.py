import pandas as pd
import json
import os
import ast

for file in os.listdir('financial_data'):
    if 'Capital_Ledger' in file and file.endswith('.csv'):
        path = os.path.join('financial_data', file)
        try:
            df = pd.read_csv(path)
            if 'Daily_PnL_JSON' in df.columns:
                def clean_json(x):
                    try:
                        d = ast.literal_eval(str(x))
                    except:
                        try:
                            d = json.loads(str(x))
                        except:
                            d = {}
                    if 'FAKEZOMBIE' in d:
                        del d['FAKEZOMBIE']
                    return json.dumps(d)
                
                df['Daily_PnL_JSON'] = df['Daily_PnL_JSON'].apply(clean_json)
                df.to_csv(path, index=False)
                print(f"Cleaned {file}")
        except Exception as e:
            print(f"Failed {file}: {e}")
