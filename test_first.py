import sys; sys.path.append('c:\\Users\\AviShemla\\AntiGravity'); from dotenv import load_dotenv; load_dotenv(); import database_manager as dbm;
for p in ['Conservative', 'Neutral', 'Dynamic', 'BallsForBrains', 'Conservative ETF', 'Neutral ETF', 'Dynamic ETF', 'BallsForBrains ETF']:
    try:
        df = dbm.get_ledger(p)
        if not df.empty:
            print(f'{p}: First Date={df.iloc[0]["Date"]}, First Equity={df.iloc[0]["Total_Realized_PnL"]}')
    except Exception as e:
        print(f'{p}: ERR')
