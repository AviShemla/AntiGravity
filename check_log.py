import re

log_path = r'C:\Users\AviShemla\.gemini\antigravity\brain\e6da8969-1069-4402-8307-e101b4874b0c\.system_generated\tasks\task-7278.log'
try:
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        data = f.read()
        
    c_champ = data.count('tmp_pred_CHAMPION.json')
    c_cap = data.count('tmp_pred_EL_CAP.json')
    c_vol = data.count('tmp_pred_EL_VOLTI.json')
    
    print(f"CHAMPION: {c_champ}/20 days processed")
    print(f"EL_CAP: {c_cap}/20 days processed")
    print(f"EL_VOLTI: {c_vol}/20 days processed")
    
    # Check the latest target date
    matches = re.findall(r'Target Date: ([\d\-]+)', data)
    if matches:
        print(f"Current Target Date: {matches[-1]}")
    
    # Check tickers processed for latest
    matches2 = re.findall(r'Processed (\d+) tickers', data)
    if matches2:
        print(f"Latest batch tickers processed: {matches2[-1]}")
        
except Exception as e:
    print(f"Error reading log: {e}")
