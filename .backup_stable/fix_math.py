import pandas as pd
import json

path = 'financial_data/Capital_Ledger_BallsForBrains.csv'
df = pd.read_csv(path)

# Drop any rows after 05-28
df['Date'] = pd.to_datetime(df['Date'])
df = df[df['Date'] <= '2026-05-28']
df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')

# Remove FAKEZOMBIE from 05-28 Holdings_JSON
def remove_zombie(x):
    try:
        d = json.loads(x)
        if 'FAKEZOMBIE' in d:
            del d['FAKEZOMBIE']
        return json.dumps(d)
    except:
        return x

df['Holdings_JSON'] = df['Holdings_JSON'].apply(remove_zombie)
df.to_csv(path, index=False)
print("Cleaned BallsForBrains 05-28 Holdings")
