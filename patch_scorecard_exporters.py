import os
import re

files_to_patch = [
    r"C:\Users\AviShemla\AntiGravity\export_bayesian_scorecard_formatted.py",
    r"C:\Users\AviShemla\AntiGravity\export_etf_scorecard.py",
    r"C:\Users\AviShemla\AntiGravity\export_bayesian_scorecard_TNX.py",
    r"C:\Users\AviShemla\AntiGravity\virtual_broker.py",
    r"C:\Users\AviShemla\AntiGravity\etf_virtual_broker.py"
]

def patch_file(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Scorecard patching
    p1 = r"""            import glob\s*import json\s*ledger_files = glob.glob\(r'.*?_Ledger_\*\.csv'\)\s*for lf in ledger_files:\s*df_l = pd.read_csv\(lf\)"""
    r1 = """            import sys
            sys.path.insert(0, r"C:\\Users\\AviShemla\\AntiGravity")
            import database_manager
            import json
            for p in ["Conservative", "Neutral", "BallsForBrains", "Dynamic"]:
                df_l = database_manager.get_ledger(p)"""
    content = re.sub(p1, lambda m: r1, content)
    
    # ETF Scorecard patching
    p2 = r"""        ledger_files = glob\.glob\(os\.path\.join\(BASE_DIR, 'ETF_Capital_Ledger_\*\.csv'\)\)\s*for lf in ledger_files:\s*try:\s*df_l = pd\.read_csv\(lf\)"""
    r2 = """        import database_manager
        for p in ["Conservative", "Neutral", "BallsForBrains", "Dynamic"]:
            try:
                df_l = database_manager.get_ledger(f"ETF_{p}")"""
    content = re.sub(p2, lambda m: r2, content)

    # Virtual Broker patching
    content = re.sub(r'^\s*ledger_path = os\.path\.join\(BASE_DIR, f\'Capital_Ledger_\{persona_name\}\.csv\'\)\n', '', content, flags=re.MULTILINE)
    content = re.sub(r'^\s*ledger_path = os\.path\.join\(BASE_DIR, f\'ETF_Capital_Ledger_\{persona_name\}\.csv\'\)\n', '', content, flags=re.MULTILINE)
    content = re.sub(r'\s*"Ledger_Path": ledger_path,', '', content, flags=re.MULTILINE)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Successfully patched {filepath}")

for f in files_to_patch:
    patch_file(f)

