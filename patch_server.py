import re
import os

SERVER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'server.py')

with open(SERVER_PATH, "r") as f:
    content = f.read()

# 1. Add database_manager import
if "import database_manager" not in content:
    content = content.replace("import datetime\n", "import datetime\nimport database_manager\n")

# 2. Patch /api/holdings
content = re.sub(
    r'    if mode == "Single":\n        path = os.path.join\(BASE_DIR, f\'Capital_Ledger_\{persona\}\.csv\'\)\n    else:\n        path = os.path.join\(BASE_DIR, f\'ETF_Capital_Ledger_\{persona\}\.csv\'\)\n        \n    if not os.path.exists\(path\):\n        raise HTTPException\(status_code=404, detail="Ledger not found"\)\n        \n    df = pd.read_csv\(path\)',
    '    p_name = persona if mode == "Single" else f"ETF_{persona}"\n    df = database_manager.get_ledger(p_name)\n    if df.empty:\n        raise HTTPException(status_code=404, detail="Ledger not found")',
    content
)

# 3. Patch /api/race
content = re.sub(
    r'        if mode == "Single":\n            lp = os.path.join\(BASE_DIR, f\'Capital_Ledger_\{p\}\.csv\'\)\n        else:\n            lp = os.path.join\(BASE_DIR, f\'ETF_Capital_Ledger_\{p\}\.csv\'\)\n            \n        if os.path.exists\(lp\):\n            df_p = pd.read_csv\(lp\)',
    '        p_name = p if mode == "Single" else f"ETF_{p}"\n        df_p = database_manager.get_ledger(p_name)\n        if not df_p.empty:',
    content
)

# 4. Patch /api/dropdown
content = re.sub(
    r'    ledger_path = os.path.join\(BASE_DIR, f\'Capital_Ledger_\{persona\}\.csv\' if mode == \'Single\' else f\'ETF_Capital_Ledger_\{persona\}\.csv\'\)\n    if os.path.exists\(ledger_path\):\n        try:\n            df = pd.read_csv\(ledger_path\)',
    '    p_name = persona if mode == "Single" else f"ETF_{persona}"\n    try:\n        df = database_manager.get_ledger(p_name)\n        if not df.empty:',
    content
)

# 5. Patch /api/bayesian
content = re.sub(
    r'            lp = os.path.join\(BASE_DIR, f\'Capital_Ledger_\{p\}\.csv\' if mode == \'Single\' else f\'ETF_Capital_Ledger_\{p\}\.csv\'\)\n            if os.path.exists\(lp\):\n                df_p = pd.read_csv\(lp\)',
    '            p_name = p if mode == "Single" else f"ETF_{p}"\n            df_p = database_manager.get_ledger(p_name)\n            if not df_p.empty:',
    content
)

# 6. Patch /api/autopsy
content = re.sub(
    r'    stock_ledger = os.path.join\(BASE_DIR, \'Capital_Ledger_BallsForBrains\.csv\'\)\n    etf_ledger = os.path.join\(BASE_DIR, \'ETF_Capital_Ledger_BallsForBrains\.csv\'\)\n    \n    def process_ledger\(path, persona="BallsForBrains"\):\n        if not os.path.exists\(path\):\n            return \{"serial_offenders": \[\], "day_vulnerability": \[\], "forensic_ledger": \[\]\}\n            \n        df = pd.read_csv\(path\)',
    '    def process_ledger(persona_id):\n        df = database_manager.get_ledger(persona_id)\n        if df.empty:\n            return {"serial_offenders": [], "day_vulnerability": [], "forensic_ledger": []}',
    content
)

content = content.replace(
    '        stock_data = process_ledger(stock_ledger)\n        etf_data = process_ledger(etf_ledger)',
    '        stock_data = process_ledger("BallsForBrains")\n        etf_data = process_ledger("ETF_BallsForBrains")'
)

with open(SERVER_PATH, "w") as f:
    f.write(content)

print("[SUCCESS] Fast API backend patched to query SQLite.")
