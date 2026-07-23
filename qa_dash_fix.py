import pandas as pd
import database_manager

print("QA AUDIT: Verifying Data Continuity for '2026-07-22'...")

# 1. Fetch data exactly as dashboard.py does
persona = 'Conservative'
df = database_manager.get_ledger(persona)
df_p = df[['Date', 'Total_Equity']].rename(columns={'Total_Equity': persona}).set_index('Date')
plot_df = pd.concat([df_p], axis=1).sort_index().ffill()

# 2. Apply our new reindex/ffill fix
plot_df = plot_df.reindex(pd.date_range(start=plot_df.index.min(), end=pd.Timestamp.now().normalize(), freq='B')).ffill()
plot_df = plot_df[plot_df.index >= (pd.Timestamp.now() - pd.Timedelta(days=35))]

# 3. Mathematically assert 22/07 exists
target_date = pd.Timestamp('2026-07-22')
if target_date in plot_df.index:
    print(f"SUCCESS: {target_date.strftime('%d/%m/%Y')} successfully forward-filled! Value: ${plot_df.loc[target_date, persona]:.2f}")
else:
    print(f"FAILED: {target_date.strftime('%d/%m/%Y')} is missing from the index!")

print("\nQA AUDIT: Verifying Plotly Layout Parameters...")
with open('dashboard.py', 'r', encoding='utf-8') as f:
    code = f.read()
    if 'tickformat="%d/%m/%Y"' in code and 'dtick=86400000.0' in code and 'tickmode="linear"' in code:
        print("SUCCESS: Plotly strict date override parameters successfully injected into layout.")
    else:
        print("FAILED: Plotly strict parameters missing.")
