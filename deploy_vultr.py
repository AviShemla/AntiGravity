import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('66.42.118.26', username='root', password='M,w5_=k@eHA!ecEK')

commands = [
    '''cd /opt/antigravity && ./venv/bin/python3 -c "
import database_manager as dbm, json
trades_generated = False
for p in ['Conservative', 'Neutral', 'Dynamic', 'BallsForBrains', 'ETF_Conservative', 'ETF_Neutral', 'ETF_Dynamic', 'ETF_BallsForBrains']:
    try:
        df = dbm.get_ledger(p)
        if df.empty: continue
        last_row = df.iloc[-1]
        last_holdings = json.loads(last_row['Holdings_JSON'])
        pending = dbm.get_pending_order(p)
        if pending and pending.get('date') >= str(last_row['Date']):
            target_holdings = json.loads(pending['target_holdings_json'])
            
            diffs = {}
            all_assets = set(last_holdings.keys()).union(set(target_holdings.keys()))
            all_assets.discard('Cash')
            for a in all_assets:
                old = last_holdings.get(a, 0)
                old_val = float(old.get('dollars', 0)) if isinstance(old, dict) else float(old)
                new = target_holdings.get(a, 0)
                new_val = float(new.get('dollars', 0)) if isinstance(new, dict) else float(new)
                if abs(new_val - old_val) > 1.0:
                    diffs[a] = {'from': old_val, 'to': new_val}
            
            if diffs:
                print(f'{p} TRADES FOR TOMORROW: {diffs}')
                trades_generated = True
    except Exception as e:
        pass
if not trades_generated:
    print('ZERO TRADES GENERATED ACROSS ALL PERSONAS FOR TOMORROW.')
"'''
]

for cmd in commands:
    print(f"Executing: {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    print("STDOUT:", stdout.read().decode())
    print("STDERR:", stderr.read().decode())

ssh.close()
