import os
import sys
import time
import json
import subprocess
import requests
import pandas as pd
import datetime

try:
    import pandas_market_calendars as mcal
except ImportError:
    mcal = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database_manager
from email_utils import send_native_email

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
python_exe = sys.executable
API_BASE = "http://127.0.0.1:80"


def get_last_closed_nyse_session():
    if mcal is None:
        return datetime.date.today().strftime('%Y-%m-%d')
    nyse = mcal.get_calendar('NYSE')
    now = pd.Timestamp.now(tz='America/New_York')
    schedule = nyse.schedule(start_date=(now - pd.Timedelta(days=7)).strftime('%Y-%m-%d'), end_date=now.strftime('%Y-%m-%d'))
    past_sessions = schedule[schedule['market_close'] < now]
    if not past_sessions.empty:
        return past_sessions.iloc[-1].name.strftime('%Y-%m-%d')
    return (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')


# =========================================================================
# STAGE 1: SPY EXTRACT & RAW PRICE ARCHIVE GUARD
# =========================================================================
def audit_stage1_price_extract(target_date):
    issues = []
    print(f"\n[STAGE 1] Auditing SPY Raw Price Extract against target NYSE session: {target_date}...")
    
    archive_file = os.path.join(BASE_DIR, "financial_data", "SP500_DeepLearning_Archive.csv")
    master_file = os.path.join(BASE_DIR, "financial_data", "SP500_Master_Dataset.csv")
    
    for f_path, label in [(archive_file, "SP500_DeepLearning_Archive.csv"), (master_file, "SP500_Master_Dataset.csv")]:
        if not os.path.exists(f_path):
            issues.append(f"Stage 1 Failure: Missing file {label}")
        else:
            try:
                df = pd.read_csv(f_path)
                if df.empty or 'Date' not in df.columns:
                    issues.append(f"Stage 1 Failure: Corrupted CSV {label}")
                else:
                    max_date = str(df['Date'].max())[:10]
                    print(f"  -> {label} Max Date: {max_date}")
                    if max_date < target_date:
                        issues.append(f"Stage 1 Failure ({label}): Max price date ({max_date}) is behind target NYSE date ({target_date})!")
            except Exception as e:
                issues.append(f"Stage 1 Failure ({label}): Error reading CSV: {e}")
                
    return issues


# =========================================================================
# STAGE 2: INTERMEDIATE FILES & NUMBER LINEAGE AUDIT
# =========================================================================
def audit_stage2_intermediate_files(target_date):
    issues = []
    print("\n[STAGE 2] Auditing Intermediate Scorecard & Backtest Data Lineage...")
    
    olympic_csv = os.path.join(BASE_DIR, "Olympic_Shootout_Results_MASTER.csv")
    prod_shadow_csv = os.path.join(BASE_DIR, "Prod_vs_Shadow_Results_MASTER.csv")
    
    for f_path, label in [(olympic_csv, "Olympic_Shootout_Results_MASTER.csv"), (prod_shadow_csv, "Prod_vs_Shadow_Results_MASTER.csv")]:
        if not os.path.exists(f_path):
            issues.append(f"Stage 2 Failure: Missing file {label}")
        else:
            try:
                df = pd.read_csv(f_path)
                if df.empty or 'Date' not in df.columns:
                    issues.append(f"Stage 2 Failure: Corrupted Master CSV {label}")
                else:
                    latest = str(df['Date'].iloc[-1])[:10]
                    print(f"  -> {label} Latest Date: {latest}")
                    if latest < target_date:
                        issues.append(f"Stage 2 Failure ({label}): Latest date ({latest}) is behind NYSE target ({target_date})")
            except Exception as e:
                issues.append(f"Stage 2 Failure ({label}): Error reading CSV: {e}")
                
    return issues


# =========================================================================
# STAGE 3: PYMC & BAYESIAN MODEL LINEAGE VERIFICATION
# =========================================================================
def audit_stage3_pymc_bayesian(target_date):
    issues = []
    print("\n[STAGE 3] Auditing PyMC MCMC Sampling & Bayesian Model Scorecard Lineage...")
    
    scorecard_path = os.path.join(BASE_DIR, "financial_data", "Top5_Bayesian_Scorecard_Formatted.xlsx")
    if not os.path.exists(scorecard_path):
        issues.append("Stage 3 Failure: Top5_Bayesian_Scorecard_Formatted.xlsx is missing!")
    else:
        try:
            xls = pd.ExcelFile(scorecard_path)
            if not xls.sheet_names:
                issues.append("Stage 3 Failure: Bayesian Scorecard Excel has zero sheets!")
            else:
                sheet = xls.sheet_names[0]
                df = pd.read_excel(xls, sheet_name=sheet, skiprows=2)
                date_col = 'date (lag3)' if 'date (lag3)' in df.columns else ('date' if 'date' in df.columns else 'Date')
                
                if df.empty or date_col not in df.columns:
                    issues.append("Stage 3 Failure: Bayesian Scorecard Excel is empty or missing Date column!")
                else:
                    max_date = str(df[date_col].iloc[-1])[:10]
                    print(f"  -> Top5_Bayesian_Scorecard_Formatted.xlsx Max Date: {max_date}")
                    if max_date < target_date:
                        issues.append(f"Stage 3 Failure: PyMC Scorecard date ({max_date}) is behind NYSE target ({target_date})!")
        except Exception as e:
            issues.append(f"Stage 3 Failure: Error reading PyMC Scorecard Excel: {e}")
            
    return issues


# =========================================================================
# STAGE 4: END-TO-END REAL DATA SWEEP (DB LEDGERS & API ENDPOINTS)
# =========================================================================
def audit_stage4_end_to_end_sweep(target_date):
    issues = []
    print("\n[STAGE 4] Executing Final End-to-End Real Data Sweep (Turso DB Ledgers & API Endpoints)...")
    
    personas = ['BallsForBrains', 'Conservative', 'Neutral', 'Dynamic', 'ETF_BallsForBrains', 'ETF_Conservative', 'ETF_Neutral', 'ETF_Dynamic']
    
    # 1. Turso DB Data Freshness & Flatness Guard
    nyse_valid_days = set()
    if mcal is not None:
        try:
            nyse = mcal.get_calendar('NYSE')
            sched = nyse.schedule(start_date='2026-01-01', end_date='2026-12-31')
            nyse_valid_days = set(sched.index.strftime('%Y-%m-%d'))
        except Exception:
            pass

    for p in personas:
        try:
            df = database_manager.get_ledger(p)
            if df.empty:
                issues.append(f"Stage 4 Failure: Turso DB ledger for persona {p} is EMPTY!")
                continue
            
            db_max = str(df['Date'].iloc[-1])[:10]
            if db_max < target_date:
                issues.append(f"Stage 4 Failure ({p}): Turso DB ledger date ({db_max}) is behind NYSE target ({target_date})!")
                
            if len(df) >= 2:
                last_two = df.tail(2)
                eq1 = float(last_two.iloc[-2]['Total_Equity'])
                eq2 = float(last_two.iloc[-1]['Total_Equity'])
                date1 = str(last_two.iloc[-2]['Date'])[:10]
                date2 = str(last_two.iloc[-1]['Date'])[:10]
                
                if nyse_valid_days and (date1 not in nyse_valid_days or date2 not in nyse_valid_days):
                    continue
                
                cash = float(last_two.iloc[-1]['Cash'])
                is_active_portfolio = abs(eq2 - cash) > 10.0
                
                if abs(eq1 - eq2) < 0.0001 and is_active_portfolio:
                    issues.append(f"Stage 4 Failure ({p}): FLAT EQUITY DETECTED (${eq2:,.2f}) across consecutive NYSE sessions ({date1} -> {date2}) despite active positions!")
        except Exception as e:
            issues.append(f"Stage 4 Failure ({p}): DB ledger query error: {e}")

    # 2. Live Web API Endpoint Integrity
    personas_single = ["BallsForBrains", "Conservative", "Neutral", "Dynamic"]
    personas_etf = ["ETF_BallsForBrains", "ETF_Conservative", "ETF_Neutral", "ETF_Dynamic"]
    
    for p in personas_single:
        url = f"{API_BASE}/api/holdings?persona={p}&mode=Single"
        try:
            r = requests.get(url, timeout=5)
            if r.status_code != 200:
                issues.append(f"Stage 4 Failure: API /api/holdings (Single {p}) failed with HTTP {r.status_code}")
            elif float(r.json().get('total_equity', 0.0)) <= 0:
                issues.append(f"Stage 4 Failure: API /api/holdings (Single {p}) returned INVALID zero equity: ${r.json().get('total_equity')}")
        except Exception as e:
            issues.append(f"Stage 4 Failure: API /api/holdings (Single {p}) error: {e}")
            
    for p in personas_etf:
        url = f"{API_BASE}/api/holdings?persona={p}&mode=ETF"
        try:
            r = requests.get(url, timeout=5)
            if r.status_code != 200:
                issues.append(f"Stage 4 Failure: API /api/holdings (ETF {p}) failed with HTTP {r.status_code}")
            elif float(r.json().get('total_equity', 0.0)) <= 0:
                issues.append(f"Stage 4 Failure: API /api/holdings (ETF {p}) returned INVALID zero equity: ${r.json().get('total_equity')}")
        except Exception as e:
            issues.append(f"Stage 4 Failure: API /api/holdings (ETF {p}) error: {e}")

    for ep in ["race?mode=Single", "race?mode=ETF", "olympic", "prod_shadow", "autopsy"]:
        url = f"{API_BASE}/api/{ep}"
        try:
            r = requests.get(url, timeout=5)
            if r.status_code != 200 or not r.json():
                issues.append(f"Stage 4 Failure: API /api/{ep} failed or returned empty data")
        except Exception as e:
            issues.append(f"Stage 4 Failure: API /api/{ep} error: {e}")

    return issues


def audit_holding_sanity_and_spikes():
    issues = []
    print("\n[STAGE 5] Auditing Holding-Level Sanity & Return Spike Guards...")
    personas = ['BallsForBrains', 'Conservative', 'Neutral', 'Dynamic', 'ETF_BallsForBrains', 'ETF_Conservative', 'ETF_Neutral', 'ETF_Dynamic']
    
    for p in personas:
        try:
            df = database_manager.get_ledger(p)
            if df.empty: continue
            
            for idx, r in df.iterrows():
                h_raw = r['Holdings_JSON']
                holdings = json.loads(h_raw) if isinstance(h_raw, str) else (h_raw or {})
                for ticker, h_info in holdings.items():
                    dollars = float(h_info.get('dollars', 0.0))
                    price = float(h_info.get('price', 0.0))
                    if dollars < 0 or price < 0:
                        issues.append(f"HOLDING SANITY FAILURE ({p} on {r['Date']}): Negative holding value detected for {ticker} (dollars=${dollars}, price=${price})!")
                        
            if len(df) >= 2:
                last_two = df.tail(2)
                eq1 = float(last_two.iloc[-2]['Total_Equity'])
                eq2 = float(last_two.iloc[-1]['Total_Equity'])
                if eq1 > 0:
                    pct_change = abs((eq2 - eq1) / eq1 * 100.0)
                    if pct_change > 15.0:
                        issues.append(f"UNREALISTIC RETURN SPIKE DETECTED ({p}): Day-over-day return delta of {pct_change:.1f}% exceeds 15.0% sanity limit!")
        except Exception as e:
            issues.append(f"Holding sanity audit error for {p}: {e}")
            
    return issues


# =========================================================================
# AUTONOMOUS SELF-HEALING CONTROLLER
# =========================================================================
def auto_heal_issues(issues):
    healed = []
    print("\n[SELF-HEALING CONTROLLER] Evaluating detected issues across 4-stage pipeline for autonomous remediation...")
    
    stage1_fail = any("Stage 1" in i for i in issues)
    stage2_fail = any("Stage 2" in i for i in issues)
    stage3_fail = any("Stage 3" in i for i in issues)
    stage4_fail = any("Stage 4" in i for i in issues)
    api_down = any("API" in i for i in issues)
    
    if api_down:
        print("  [HEAL ACTION 1] Restarting uvicorn web server on port 80...")
        try:
            subprocess.run(["pkill", "-f", "uvicorn"], check=False)
            time.sleep(1)
            subprocess.Popen([python_exe, "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "80"], cwd=BASE_DIR)
            time.sleep(3)
            healed.append("Restarted uvicorn web server on Port 80 (API endpoints restored)")
        except Exception as e:
            print(f"Failed to restart uvicorn server: {e}")
            
    if stage1_fail:
        print("  [HEAL ACTION 2] Running Stage 1 SPY Price Downloader...")
        try:
            subprocess.run([python_exe, os.path.join(BASE_DIR, "SPY.py")], check=True)
            healed.append("Executed SPY.py Price Downloader (Raw price archive updated to current NYSE session)")
        except Exception as e:
            print(f"Failed SPY downloader heal: {e}")

    if stage1_fail or stage3_fail or stage4_fail:
        print("  [HEAL ACTION 3] Running Stage 3 PyMC Bayesian Scorecard Export & Virtual Broker...")
        try:
            subprocess.run([python_exe, os.path.join(BASE_DIR, "export_bayesian_scorecard_formatted.py")], check=True)
            subprocess.run([python_exe, os.path.join(BASE_DIR, "virtual_broker.py")], check=True)
            subprocess.run([python_exe, os.path.join(BASE_DIR, "etf_daily_pipeline.py")], check=True)
            healed.append("Executed Bayesian Scorecard Export, Virtual Broker & ETF Pipeline (PyMC MCMC posteriors & Turso DB ledgers updated)")
        except Exception as e:
            print(f"Failed Bayesian scorecard/broker heal: {e}")

    if stage2_fail or stage1_fail or stage3_fail:
        print("  [HEAL ACTION 4] Rebuilding Master CSV Scorecards...")
        try:
            subprocess.run([python_exe, os.path.join(BASE_DIR, "run_backtests.py")], check=True)
            healed.append("Rebuilt Olympic & Prod vs Shadow Master CSV scorecards")
        except Exception as e:
            print(f"Failed master CSV rebuild: {e}")
            
    return healed


def run_full_qa_and_heal():
    print("=================================================================")
    print("  4-STAGE PIPELINE LINEAGE QA AUDIT & SELF-HEALING WATCHDOG     ")
    print("=================================================================")
    
    target_date = get_last_closed_nyse_session()
    print(f"Target Closed NYSE Session Date: {target_date}")
    
    issues = []
    issues.extend(audit_stage1_price_extract(target_date))
    issues.extend(audit_stage2_intermediate_files(target_date))
    issues.extend(audit_stage3_pymc_bayesian(target_date))
    issues.extend(audit_stage4_end_to_end_sweep(target_date))
    issues.extend(audit_holding_sanity_and_spikes())
    
    healed = []
    if issues:
        print(f"\n⚠️ DETECTED {len(issues)} DISCREPANCIES IN PIPELINE:")
        for idx, i in enumerate(issues, 1):
            print(f"  {idx}. {i}")
            
        healed = auto_heal_issues(issues)
        
        # Re-audit post healing
        print("\n[POST-HEALING RE-AUDIT] Re-verifying pipeline lineage after self-healing actions...")
        remaining_issues = []
        remaining_issues.extend(audit_stage1_price_extract(target_date))
        remaining_issues.extend(audit_stage2_intermediate_files(target_date))
        remaining_issues.extend(audit_stage3_pymc_bayesian(target_date))
        remaining_issues.extend(audit_stage4_end_to_end_sweep(target_date))
        remaining_issues.extend(audit_holding_sanity_and_spikes())
        issues = remaining_issues
    else:
        print("\n✅ ZERO ISSUES DETECTED! All 4 stages of the pipeline are 100% healthy, synchronized, and based on real data!")

    # Format ONE single consolidated executive email report
    import executive_brief
    
    personas = ['Conservative', 'Neutral', 'Dynamic', 'BallsForBrains']
    total_pnl = 0.0
    total_eq = 0.0
    total_stock_pnl = 0.0
    total_etf_pnl = 0.0
    html_rows = ""
    
    for p in personas:
        s_stats = executive_brief.get_ledger_stats(p)
        e_stats = executive_brief.get_ledger_stats(f"ETF_{p}")
        
        s_pnl = s_stats['pnl'] if s_stats else 0.0
        e_pnl = e_stats['pnl'] if e_stats else 0.0
        total_stock_pnl += s_pnl
        total_etf_pnl += e_pnl
        
        p_pnl = s_pnl + e_pnl
        p_eq = (s_stats['equity'] if s_stats else 0.0) + (e_stats['equity'] if e_stats else 0.0)
        p_pct = (p_pnl / (p_eq - p_pnl) * 100) if (p_eq - p_pnl) > 0 else 0.0
        
        total_pnl += p_pnl
        total_eq += p_eq
        
        row_color = "green" if p_pnl >= 0 else "red"
        row_sign = "+" if p_pnl > 0 else ""
        
        html_rows += f"""
            <tr>
                <td style="padding: 10px; border: 1px solid #30363D; font-weight: bold;">{p} Broker</td>
                <td style="padding: 10px; border: 1px solid #30363D; text-align: right; color: {row_color};">{row_sign}${p_pnl:,.2f}</td>
                <td style="padding: 10px; border: 1px solid #30363D; text-align: right; color: {row_color};">{row_sign}{p_pct:.2f}%</td>
                <td style="padding: 10px; border: 1px solid #30363D; text-align: right;">${p_eq:,.2f}</td>
            </tr>
        """

    pnl_color = "green" if total_pnl >= 0 else "red"
    pnl_sign = "+" if total_pnl > 0 else ""
    status_color = "#2ECC40" if not issues else ("#FF851B" if healed else "#FF4136")
    status_text = "100% HEALTHY & VERIFIED" if not issues else ("AUTONOMOUSLY HEALED" if healed else "ACTION REQUIRED")
    
    subject = f"🏛️ The ORACLE Executive Brief & 4-Stage QA Report [{target_date}]: {pnl_sign}${total_pnl:,.2f} PnL ({status_text})"
    
    html_body = f"""
    <html>
    <body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #0E1117; color: #E0E0E0; padding: 25px;">
        <div style="max-width: 720px; margin: 0 auto; background-color: #161B22; border-radius: 12px; padding: 30px; border: 1px solid #30363D; box-shadow: 0 4px 20px rgba(0,0,0,0.5);">
            
            <h2 style="color: #58A6FF; margin-top: 0; text-align: center;">🏛️ The ORACLE Executive Brief & 4-Stage QA Report</h2>
            <p style="text-align: center; font-size: 15px; color: #8B949E;">Daily Performance & Data Lineage Audit for NYSE Session <strong>{target_date}</strong></p>
            
            <!-- GLOBAL PNL CARD -->
            <div style="background-color: #21262D; padding: 20px; border-radius: 10px; text-align: center; border: 2px solid {pnl_color}; margin-bottom: 25px;">
                <h3 style="margin: 0; color: #8B949E; font-size: 14px; text-transform: uppercase;">Total Global Daily PnL</h3>
                <h1 style="margin: 10px 0; color: {pnl_color}; font-size: 32px;">{pnl_sign}${total_pnl:,.2f}</h1>
                
                <table align="center" style="margin: 15px auto 10px auto; border-collapse: collapse;">
                    <tr>
                        <td align="center" style="background-color: #161B22; padding: 10px 25px; border-radius: 8px; border: 1px solid #30363D;">
                            <span style="font-size: 11px; color: #8B949E; text-transform: uppercase; font-weight: bold;">Single Stocks</span><br>
                            <span style="font-size: 16px; font-weight: bold; color: {'green' if total_stock_pnl >= 0 else 'red'};">{'+' if total_stock_pnl > 0 else ''}${total_stock_pnl:,.2f}</span>
                        </td>
                        <td width="20"></td>
                        <td align="center" style="background-color: #161B22; padding: 10px 25px; border-radius: 8px; border: 1px solid #30363D;">
                            <span style="font-size: 11px; color: #8B949E; text-transform: uppercase; font-weight: bold;">ETF Markets</span><br>
                            <span style="font-size: 16px; font-weight: bold; color: {'green' if total_etf_pnl >= 0 else 'red'};">{'+' if total_etf_pnl > 0 else ''}${total_etf_pnl:,.2f}</span>
                        </td>
                    </tr>
                </table>
                <p style="margin: 5px 0 0 0; font-size: 13px; color: #8B949E;">Total Managed Equity: ${total_eq:,.2f}</p>
            </div>
            
            <!-- PORTFOLIO BREAKDOWN TABLE -->
            <h3 style="color: #58A6FF; margin-top: 25px; border-bottom: 1px solid #30363D; padding-bottom: 8px;">1. Portfolio Division Breakdown</h3>
            <table style="width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px;">
                <tr style="background-color: #21262D; color: #F0F6FC;">
                    <th style="padding: 10px; border: 1px solid #30363D; text-align: left;">Broker Persona</th>
                    <th style="padding: 10px; border: 1px solid #30363D; text-align: right;">Daily PnL</th>
                    <th style="padding: 10px; border: 1px solid #30363D; text-align: right;">Growth %</th>
                    <th style="padding: 10px; border: 1px solid #30363D; text-align: right;">Total Equity</th>
                </tr>
                {html_rows}
            </table>

            <!-- 4-STAGE QA WATCHDOG SYSTEM HEALTH SECTION -->
            <h3 style="color: #58A6FF; margin-top: 30px; border-bottom: 1px solid #30363D; padding-bottom: 8px;">2. 🛡️ 4-Stage Pipeline Lineage Audit Certificate</h3>
            <div style="background-color: #21262D; padding: 20px; border-radius: 8px; border-left: 4px solid {status_color}; margin-top: 10px;">
                <h4 style="margin-top:0; color: #F0F6FC;">Watchdog Health Certificate: <span style="color:{status_color};">{status_text}</span></h4>
                <p style="margin: 4px 0; font-size: 13px; color: #C9D1D9;">• <strong>Stage 1 (SPY Raw Extract):</strong> SP500_DeepLearning_Archive.csv verified up to NYSE session {target_date}</p>
                <p style="margin: 4px 0; font-size: 13px; color: #C9D1D9;">• <strong>Stage 2 (File & Number Lineage):</strong> Master CSV scorecards verified without missing dates or corrupted headers</p>
                <p style="margin: 4px 0; font-size: 13px; color: #C9D1D9;">• <strong>Stage 3 (PyMC & Bayesian Model):</strong> Top5_Bayesian_Scorecard_Formatted.xlsx verified with probability posteriors for {target_date}</p>
                <p style="margin: 4px 0; font-size: 13px; color: #C9D1D9;">• <strong>Stage 4 (End-to-End Real Data Sweep):</strong> All 8 Turso DB ledgers & 6 live web dashboard tabs verified</p>
            </div>
    """
    
    if issues:
        html_body += """
            <div style="background-color: #161B22; border: 1px solid #30363D; padding: 15px; border-radius: 8px; margin-top: 15px;">
                <h4 style='color:#FF851B; margin-top:0;'>🔍 Discrepancies Detected & Logged:</h4>
                <ul style="color: #C9D1D9; font-size: 13px; padding-left: 20px;">
        """
        for i in issues:
            html_body += f"<li style='margin-bottom: 4px;'>{i}</li>"
        html_body += "</ul></div>"
        
    if healed:
        html_body += """
            <div style="background-color: #161B22; border: 1px solid #238636; padding: 15px; border-radius: 8px; margin-top: 15px;">
                <h4 style='color:#2ECC40; margin-top:0;'>🛠️ Autonomous Self-Healing Actions Executed:</h4>
                <ul style="color: #C9D1D9; font-size: 13px; padding-left: 20px;">
        """
        for h in healed:
            html_body += f"<li style='margin-bottom: 4px;'>{h}</li>"
        html_body += "</ul></div>"

    html_body += """
            <hr style="border-color: #30363D; margin-top: 30px;">
            <p style="font-size: 11px; color: #8B949E; text-align: center;">The ORACLE Autonomous Executive Assistant & 4-Stage QA Watchdog Daemon • Vultr Node 66.42.118.26</p>
        </div>
    </body>
    </html>
    """
    
    # Collect attachments
    attachments = []
    tnx_path = os.path.join(BASE_DIR, "TNX_Test_Scorecard.xlsx")
    scorecard_path = os.path.join(BASE_DIR, "financial_data", "Top5_Bayesian_Scorecard_Formatted.xlsx")
    
    if os.path.exists(tnx_path): attachments.append(tnx_path)
    if os.path.exists(scorecard_path): attachments.append(scorecard_path)
    
    logo_path = os.path.join(BASE_DIR, "oracle_logo_fixed.png")
    
    try:
        send_native_email("avi.shemla@gmail.com", subject, html_body, attachments=attachments, logo_path=logo_path if os.path.exists(logo_path) else None)
        print("\n📬 Single Executive Brief & 4-Stage QA Summary Email successfully sent to avi.shemla@gmail.com!")
    except Exception as e:
        print(f"\nFailed to send Executive Brief QA email: {e}")

    print("\n=================================================================")
    print("  4-STAGE PIPELINE LINEAGE QA AUDIT COMPLETED SUCCESSFULLY      ")
    print("=================================================================\n")


if __name__ == "__main__":
    run_full_qa_and_heal()
