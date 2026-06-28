import re
import os

DASHBOARD_PATH = r"C:\Users\AviShemla\AntiGravity\dashboard_v1.py"
SERVER_PATH = r"C:\Users\AviShemla\AntiGravity\server.py"

def patch_file(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. get_latest_holdings
    p1 = r"""    if mode == "Single":\s*path = os.path.join\(BASE_DIR, f'Capital_Ledger_\{persona\}\.csv'\)\s*else:\s*path = os.path.join\(BASE_DIR, f'ETF_Capital_Ledger_\{persona\}\.csv'\)\s*if not os.path.exists\(path\):\s*return None, None\s*df = pd.read_csv\(path\)"""
    r1 = """    import sys
    sys.path.insert(0, r"C:\\Users\\AviShemla\\AntiGravity")
    import database_manager
    if mode == "Single":
        df = database_manager.get_ledger(persona)
    else:
        df = database_manager.get_ledger(f"ETF_{persona}")
    if df.empty:
        return None, None"""
    content = re.sub(p1, lambda m: r1, content, flags=re.MULTILINE)

    # 2. get_asset_breakdown
    p2 = r"""    if mode == "Single":\s*path = os.path.join\(BASE_DIR, f'Capital_Ledger_\{persona\}\.csv'\)\s*else:\s*path = os.path.join\(BASE_DIR, f'ETF_Capital_Ledger_\{persona\}\.csv'\)\s*if not os.path.exists\(path\):\s*return pd.DataFrame\(\)\s*df = pd.read_csv\(path\)"""
    r2 = """    import sys
    sys.path.insert(0, r"C:\\Users\\AviShemla\\AntiGravity")
    import database_manager
    if mode == "Single":
        df = database_manager.get_ledger(persona)
    else:
        df = database_manager.get_ledger(f"ETF_{persona}")
    if df.empty:
        return pd.DataFrame()"""
    content = re.sub(p2, lambda m: r2, content, flags=re.MULTILINE)

    # 3. get_losing_trades
    p3 = r"""    if mode == "Single":\s*ledger_path = os.path.join\(BASE_DIR, f'Capital_Ledger_\{persona\}\.csv'\)\s*scorecard_path = os.path.join\(BASE_DIR, 'Top5_Bayesian_Scorecard_Formatted.xlsx'\)\s*else:\s*ledger_path = os.path.join\(BASE_DIR, f'ETF_Capital_Ledger_\{persona\}\.csv'\)\s*scorecard_path = os.path.join\(BASE_DIR, 'All_ETFs_Scorecard.xlsx'\)\s*if not os.path.exists\(ledger_path\):\s*return pd.DataFrame\(\), pd.DataFrame\(\)\s*ledger = pd.read_csv\(ledger_path\)"""
    r3 = """    import sys
    sys.path.insert(0, r"C:\\Users\\AviShemla\\AntiGravity")
    import database_manager
    if mode == "Single":
        ledger = database_manager.get_ledger(persona)
        scorecard_path = os.path.join(BASE_DIR, 'Top5_Bayesian_Scorecard_Formatted.xlsx')
    else:
        ledger = database_manager.get_ledger(f"ETF_{persona}")
        scorecard_path = os.path.join(BASE_DIR, 'All_ETFs_Scorecard.xlsx')
    if ledger.empty:
        return pd.DataFrame(), pd.DataFrame()"""
    content = re.sub(p3, lambda m: r3, content, flags=re.MULTILINE)

    # 4. Single Dashboard Trial Path
    p4 = r"""            trial_path = os.path.join\(BASE_DIR, f'Capital_Ledger_\{persona_s\}\.csv'\)\s*max_dd, sharpe, win_rate, total_return = 0, 0, 0, 0\s*df_trial = pd.DataFrame\(\)\s*if os.path.exists\(trial_path\):\s*df_trial = pd.read_csv\(trial_path\)"""
    r4 = """            max_dd, sharpe, win_rate, total_return = 0, 0, 0, 0
            import sys
            sys.path.insert(0, r"C:\\Users\\AviShemla\\AntiGravity")
            import database_manager
            df_trial = database_manager.get_ledger(persona_s)
            if not df_trial.empty:"""
    content = re.sub(p4, lambda m: r4, content, flags=re.MULTILINE)

    # 5. ETF Dashboard Trial Path
    p5 = r"""            trial_path = os.path.join\(BASE_DIR, f'ETF_Capital_Ledger_\{persona_e\}\.csv'\)\s*max_dd, sharpe, win_rate, total_return = 0, 0, 0, 0\s*df_trial = pd.DataFrame\(\)\s*if os.path.exists\(trial_path\):\s*df_trial = pd.read_csv\(trial_path\)"""
    r5 = """            max_dd, sharpe, win_rate, total_return = 0, 0, 0, 0
            import sys
            sys.path.insert(0, r"C:\\Users\\AviShemla\\AntiGravity")
            import database_manager
            df_trial = database_manager.get_ledger(f"ETF_{persona_e}")
            if not df_trial.empty:"""
    content = re.sub(p5, lambda m: r5, content, flags=re.MULTILINE)

    # 6. Single Portfolio Race General
    p6 = r"""            for p in \["Conservative", "Neutral", "BallsForBrains", "Dynamic"\]:\s*lp = os.path.join\(BASE_DIR, f'Capital_Ledger_\{p\}\.csv'\)\s*if os.path.exists\(lp\):\s*df_p = pd.read_csv\(lp\)"""
    r6 = """            for p in ["Conservative", "Neutral", "BallsForBrains", "Dynamic"]:
                import sys
                sys.path.insert(0, r"C:\\Users\\AviShemla\\AntiGravity")
                import database_manager
                df_p = database_manager.get_ledger(p)
                if not df_p.empty:"""
    content = re.sub(p6, lambda m: r6, content, flags=re.MULTILINE)

    # 7. Single Portfolio Race Ticker Specific
    p7 = r"""                for p in \["Conservative", "Neutral", "BallsForBrains", "Dynamic"\]:\s*lp = os.path.join\(BASE_DIR, f'Capital_Ledger_\{p\}\.csv'\)\s*if os.path.exists\(lp\):\s*import json\s*df_p = pd.read_csv\(lp\)"""
    r7 = """                for p in ["Conservative", "Neutral", "BallsForBrains", "Dynamic"]:
                    import sys
                    sys.path.insert(0, r"C:\\Users\\AviShemla\\AntiGravity")
                    import database_manager
                    import json
                    df_p = database_manager.get_ledger(p)
                    if not df_p.empty:"""
    content = re.sub(p7, lambda m: r7, content, flags=re.MULTILINE)

    # 8. ETF Portfolio Race General
    p8 = r"""            for p in \["Conservative", "Neutral", "BallsForBrains"\]:\s*lp = os.path.join\(BASE_DIR, f'ETF_Capital_Ledger_\{p\}\.csv'\)\s*if os.path.exists\(lp\):\s*df_p = pd.read_csv\(lp\)"""
    r8 = """            for p in ["Conservative", "Neutral", "BallsForBrains"]:
                import sys
                sys.path.insert(0, r"C:\\Users\\AviShemla\\AntiGravity")
                import database_manager
                df_p = database_manager.get_ledger(f"ETF_{p}")
                if not df_p.empty:"""
    content = re.sub(p8, lambda m: r8, content, flags=re.MULTILINE)

    # 9. ETF Portfolio Race Ticker Specific
    p9 = r"""                for p in \["Conservative", "Neutral", "BallsForBrains"\]:\s*lp = os.path.join\(BASE_DIR, f'ETF_Capital_Ledger_\{p\}\.csv'\)\s*if os.path.exists\(lp\):\s*import json\s*df_p = pd.read_csv\(lp\)"""
    r9 = """                for p in ["Conservative", "Neutral", "BallsForBrains"]:
                    import sys
                    sys.path.insert(0, r"C:\\Users\\AviShemla\\AntiGravity")
                    import database_manager
                    import json
                    df_p = database_manager.get_ledger(f"ETF_{p}")
                    if not df_p.empty:"""
    content = re.sub(p9, lambda m: r9, content, flags=re.MULTILINE)
    
    # Also patch server.py if needed
    if 'server.py' in filepath:
        p10 = r"""        merged_path = os.path.join\('.*', f'Olympic_Shootout_Results_\{current_month\}\.csv'\)\s*if os.path.exists\(merged_path\):\s*df_merged = pd.read_csv\(merged_path\)"""
        r10 = """        merged_path = os.path.join('financial_data', f'Olympic_Shootout_Results_{current_month}.csv')
        if os.path.exists(merged_path):
            df_merged = pd.read_csv(merged_path)"""
        content = re.sub(p10, lambda m: r10, content, flags=re.MULTILINE)

        p11 = r"""    ledger_path = os.path.join\(EXPORT_DIR, f"Capital_Ledger_\{persona\}\.csv"\)\s*if not os.path.exists\(ledger_path\):\s*raise HTTPException\(status_code=404, detail="Ledger not found"\)\s*df = pd.read_csv\(ledger_path\)"""
        r11 = """    import database_manager
    df = database_manager.get_ledger(persona)
    if df.empty:
        raise HTTPException(status_code=404, detail="Ledger not found")"""
        content = re.sub(p11, lambda m: r11, content, flags=re.MULTILINE)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
        
    print(f"Patched {filepath}")

patch_file(DASHBOARD_PATH)
patch_file(SERVER_PATH)
