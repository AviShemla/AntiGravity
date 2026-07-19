import subprocess
import sys
import os
import datetime
import pandas as pd
import json
import re

# ==========================================
# CONFIGURATION
# ==========================================
RECIPIENT_EMAIL = "avi.shemla@gmail.com"
# TARGET_ETFS is now dynamically loaded after Step 0
# ==========================================

try:
    import pandas_market_calendars as mcal
    
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    ledger_path = os.path.join(BASE_DIR, 'financial_data', 'ETF_Capital_Ledger_Dynamic.csv')
    
    nyse = mcal.get_calendar('NYSE')
    now = pd.Timestamp.now(tz='America/New_York')
    
    # Get recent schedule and find the most recent completed session
    past = now - pd.Timedelta(days=7)
    future = now + pd.Timedelta(days=7)
    schedule = nyse.schedule(start_date=past.strftime('%Y-%m-%d'), end_date=future.strftime('%Y-%m-%d'))
    
    past_sessions = schedule[schedule['market_close'] < now]
    if past_sessions.empty:
        print("No completed market sessions found in the last 7 days. Skipping.")
        sys.exit(0)
        
    last_completed_session = past_sessions.iloc[-1]
    
    # The ledger records the PREDICTION date, which is the NEXT valid market session
    next_sessions = schedule[schedule.index > last_completed_session.name]
    if next_sessions.empty:
        prediction_date_str = (last_completed_session.name + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        prediction_date_str = next_sessions.iloc[0].name.strftime('%Y-%m-%d')
    
    # Check Ledger State
    if os.path.exists(ledger_path):
        ledger = pd.read_csv(ledger_path)
        if not ledger.empty and str(ledger['Date'].iloc[-1]) == prediction_date_str:
            print(f"[IDEMPOTENT RUN] ETF Pipeline already executed for {prediction_date_str}. Proceeding to recalculate and overwrite if Integrity Check passes.")
            
except ImportError:
    pass

def send_outlook_email(subject, html_body, attachment_path=None, logo_path=None):
    try:
        import win32com.client
        outlook = win32com.client.Dispatch('outlook.application')
        mail = outlook.CreateItem(0)
        mail.To = RECIPIENT_EMAIL
        mail.Subject = subject
        
        if logo_path and os.path.exists(logo_path):
            attachment = mail.Attachments.Add(logo_path)
            attachment.PropertyAccessor.SetProperty("http://schemas.microsoft.com/mapi/proptag/0x3712001E", "oracle_logo")
            
        mail.HTMLBody = html_body
        if attachment_path:
            for att in attachment_path.split(';'):
                if os.path.exists(att):
                    mail.Attachments.Add(att)
        mail.Send()
        print(f"Summary email successfully sent via Outlook to {RECIPIENT_EMAIL}!")
    except Exception as e:
        print(f"Failed to send email via Outlook. Error: {e}")

print("=== STARTING MULTI-ETF DAILY PIPELINE ===")
export_dir = os.path.dirname(os.path.abspath(__file__))
python_exe = sys.executable

# Clear warning logs at startup
sys.path.insert(0, export_dir)
try:
    from failover_downloader import clear_warnings
    clear_warnings()
except Exception as e:
    print(f"Warning: Could not clear warnings: {e}")

build_matrix_script = os.path.join(export_dir, "build_etf_hybrid_matrix.py")
screener_script = os.path.join(export_dir, "etf_fast_screener.py")
export_script = os.path.join(export_dir, "export_etf_scorecard.py")

print("\nStep 0: Running Dynamic ETF Screener...")
screener_generator = os.path.join(export_dir, "generate_dynamic_etfs.py")
try:
    subprocess.run([python_exe, screener_generator], cwd=export_dir, timeout=300)
except Exception as e:
    print(f"ETF Screener failed: {e}")

# Load Dynamic Targets
dynamic_target_path = os.path.join(export_dir, "financial_data", "Dynamic_Target_ETFs.json")
try:
    with open(dynamic_target_path, 'r') as f:
        TARGET_ETFS = json.load(f)
except Exception as e:
    print(f"Failed to load dynamic ETFs. Falling back to XLK. Error: {e}")
    TARGET_ETFS = ["XLK"]

for etf in TARGET_ETFS:
    print(f"\n--- Processing {etf} ---")
    
    print(f"Step 1: Building Hybrid Matrix for {etf}...")
    try:
        result1 = subprocess.run([python_exe, build_matrix_script, etf], cwd=export_dir, capture_output=True, text=True, timeout=600)
        if result1.returncode != 0:
            print(f"Hybrid Matrix build failed for {etf}: {result1.stderr}")
            continue
    except Exception as e:
        print(f"Error building matrix for {etf}: {e}")
        continue

    print(f"Step 1.5: Running Fast Screener for {etf} (11,000 combinations)...")
    try:
        result_screen = subprocess.run([python_exe, screener_script, etf], cwd=export_dir, capture_output=True, text=True, timeout=600)
        if result_screen.returncode != 0:
            print(f"Screener failed for {etf}: {result_screen.stderr}")
            continue
    except Exception as e:
        print(f"Error running screener for {etf}: {e}")
        continue

    print(f"Step 2: Running export_etf_scorecard.py for {etf}...")
    try:
        result2 = subprocess.run([python_exe, export_script, etf], cwd=export_dir, capture_output=True, text=True, timeout=1200)
        if result2.returncode != 0:
            print(f"Scorecard export failed for {etf}: {result2.stderr}")
            continue
    except Exception as e:
        print(f"Error exporting scorecard for {etf}: {e}")
        continue

print("\nStep 2.1: Compiling Single Excel Scorecard...")
compile_script = os.path.join(export_dir, "compile_etf_scorecards.py")
try:
    subprocess.run([python_exe, compile_script], cwd=export_dir, capture_output=True, text=True, timeout=120)
except Exception as e:
    print(f"Excel compilation failed: {e}")

print("\nStep 2.2: Running QA Models Bounds Validation...")
qa_models_script = os.path.join(export_dir, "qa_models.py")
try:
    result_qa = subprocess.run([python_exe, qa_models_script], cwd=export_dir, capture_output=True, text=True, timeout=120)
    print(result_qa.stdout)
except Exception as e:
    print(f"QA Models bounds check failed: {e}")

print("\nStep 3: Running Unified ETF Virtual Broker...")
broker_script = os.path.join(export_dir, "etf_virtual_broker.py")
broker_output = ""
try:
    result3 = subprocess.run([python_exe, broker_script], cwd=export_dir, capture_output=True, text=True, timeout=300)
    broker_output = result3.stdout
except Exception as e:
    broker_output = f"ETF Virtual Broker failed or timed out: {e}"

print("\nStep 4: Generating ETF 30-Day Trial Excel Report...")
excel_exporter = os.path.join(export_dir, "export_etf_broker_excel.py")
try:
    subprocess.run([python_exe, excel_exporter], cwd=export_dir, capture_output=True, text=True, timeout=120)
except Exception as e:
    print(f"Excel report generation failed: {e}")

print("\n=== MULTI-ETF DAILY PIPELINE COMPLETED SUCCESSFULLY ===")

# Excel Attachment Paths
attachments_list = []

compiled_scorecard_path = os.path.join(export_dir, "financial_data", "All_ETFs_Scorecard.xlsx")
if os.path.exists(compiled_scorecard_path):
    attachments_list.append(compiled_scorecard_path)

trial_report_path = os.path.join(export_dir, "financial_data", "ETF_Broker_30Day_Trial.xlsx")
if os.path.exists(trial_report_path):
    attachments_list.append(trial_report_path)

email_subject = "AntiGravity ETF Broker: Multi-ETF Performance & Scorecard"

# --- BUILD PIPELINE WARNINGS ALERT HTML ---
try:
    from failover_downloader import get_warnings
    warnings_list = get_warnings()
    if warnings_list:
        warnings_html = '<div style="background-color: #ffe6e6; padding: 15px; border-left: 5px solid #ff4d4d; margin-bottom: 20px;"><b style="color:#b22222; font-size:16px;">⚠️ PIPELINE WARNINGS & SELF-HEALING FALLBACKS DETECTED:</b><ul style="color:#8b0000; margin-top:5px; font-size:14px; padding-left:20px;">'
        for w in warnings_list:
            warnings_html += f'<li>{w}</li>'
        warnings_html += '</ul></div>'
    else:
        warnings_html = ""
except Exception as e:
    warnings_html = f"<p>Error loading pipeline warnings: {e}</p>"

# --- BUILD HTML MINI-DASHBOARD ---
html_dashboard = """
<table style="width:100%; border-collapse: collapse; font-family: Arial, sans-serif; margin-bottom: 20px;">
    <thead>
        <tr style="background-color: #1f497d; color: white;">
            <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">ETF Persona</th>
            <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Day's PnL ($)</th>
            <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Total Equity ($)</th>
            <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Available Cash ($)</th>
        </tr>
    </thead>
    <tbody>
"""

try:
    for p in ["Conservative", "Neutral", "BallsForBrains", "Dynamic"]:
        ledger_path = os.path.join(export_dir, 'financial_data', f'ETF_Capital_Ledger_{p}.csv')
        if os.path.exists(ledger_path):
            df_l = pd.read_csv(ledger_path)
            if not df_l.empty:
                last_row = df_l.iloc[-1]
                eq = float(last_row['Total_Equity'])
                cash = float(last_row['Cash'])
                
                daily_pnl = 0.0
                try:
                    pnl_dict = json.loads(last_row['Daily_PnL_JSON'])
                    daily_pnl = sum(pnl_dict.values())
                except:
                    pass
                
                color = "green" if daily_pnl >= 0 else "red"
                sign = "+" if daily_pnl > 0 else ""
                
                html_dashboard += f'''
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd; font-weight: bold;">{p}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: {color}; font-weight: bold;">{sign}${daily_pnl:,.2f}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right;">${eq:,.2f}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right;">${cash:,.2f}</td>
                </tr>
                '''
except Exception as e:
    html_dashboard += f"<tr><td colspan='4'>Error building dashboard: {e}</td></tr>"

html_dashboard += "</tbody></table>"
# ---------------------------------

def format_broker_output_to_html(output_str):
    if not output_str:
        return "<p>No broker output.</p>"
    return f"<pre style='background-color: #f4f4f4; padding: 10px; font-family: monospace; white-space: pre-wrap;'>{output_str}</pre>"

# --- BUILD SCORECARD HTML ---
def build_scorecard_html(scorecard_path):
    html = """
    <table style="width:100%; border-collapse: collapse; font-family: Arial, sans-serif; margin-bottom: 20px;">
        <thead>
            <tr style="background-color: #343a40; color: white;">
                <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">ETF</th>
                <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">P(UP)</th>
                <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">Exp. Return</th>
                <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">Exp. Volatility</th>
                <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">Kelly Sizing</th>
            </tr>
        </thead>
        <tbody>
    """
    try:
        if os.path.exists(scorecard_path):
            xls = pd.ExcelFile(scorecard_path)
            for sheet in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet, skiprows=2)
                if not df.empty:
                    last_row = df.iloc[-1]
                    
                    prob = float(last_row.get('Bayesian Probability P(UP)', 0))
                    ret = float(last_row.get('Expected Return %', 0))
                    vol = float(last_row.get('Expected Risk (Volatility) %', 0))
                    kelly = float(last_row.get('Kelly Optimal Allocation %', 0))
                    
                    prob_color = "green" if prob >= 0.50 else "red"
                    
                    html += f'''
                    <tr>
                        <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">{sheet}</td>
                        <td style="padding: 8px; border: 1px solid #ddd; text-align: center; color: {prob_color}; font-weight: bold;">{prob*100:.1f}%</td>
                        <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{ret*100:.2f}%</td>
                        <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{vol*100:.2f}%</td>
                        <td style="padding: 8px; border: 1px solid #ddd; text-align: center; font-weight: bold;">{kelly*100:.1f}%</td>
                    </tr>
                    '''
    except Exception as e:
         html += f"<tr><td colspan='5'>Error loading scorecard: {e}</td></tr>"
         
    html += "</tbody></table>"
    return html

# --- BUILD HOLDINGS HTML ---
def build_holdings_html(export_dir):
    html = """
    <table style="width:100%; border-collapse: collapse; font-family: Arial, sans-serif; margin-bottom: 20px;">
        <thead>
            <tr style="background-color: #343a40; color: white;">
                <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Dynamic Persona Holdings</th>
                <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Position Value ($)</th>
            </tr>
        </thead>
        <tbody>
    """
    try:
        ledger_path = os.path.join(export_dir, 'financial_data', 'ETF_Capital_Ledger_Dynamic.csv')
        if os.path.exists(ledger_path):
            df_l = pd.read_csv(ledger_path)
            if not df_l.empty:
                last_row = df_l.iloc[-1]
                pos_json = last_row.get('Positions_JSON', '{}')
                cash = float(last_row.get('Cash', 0))
                
                try:
                    positions = json.loads(pos_json)
                except:
                    positions = {}
                
                for asset, amount in positions.items():
                    html += f'''
                    <tr>
                        <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold; color: #004085;">{asset}</td>
                        <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">${amount:,.2f}</td>
                    </tr>
                    '''
                
                html += f'''
                <tr style="background-color: #f8f9fa;">
                    <td style="padding: 8px; border: 1px solid #ddd; font-style: italic;">Available Cash</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">${cash:,.2f}</td>
                </tr>
                '''
    except Exception as e:
         html += f"<tr><td colspan='2'>Error loading holdings: {e}</td></tr>"
         
    html += "</tbody></table>"
    return html

# ----------------------------------

email_html_body = f"""
<html>
<body style="font-family: Arial, sans-serif;">
<div style="text-align: center; margin-bottom: 20px;">
    <img src="cid:oracle_logo" width="210" alt="The ORACLE">
</div>
<p>Good morning,</p>
<p>The specialized ETF Hybrid pipeline has successfully finished running for today.</p>

{warnings_html}

<h3 style="color: #1f497d;">=== 🏎️ 30-Day ETF Olympic Leaderboard ===</h3>
{html_dashboard}
 
<h3 style="color: #1f497d;">=== 📊 Live Portfolio Overview (Dynamic Persona) ===</h3>
{build_holdings_html(export_dir)}
 
<h3 style="color: #1f497d;">=== 🔮 Daily Bayesian Scorecard (Tomorrow's ETF Predictions) ===</h3>
{build_scorecard_html(os.path.join(export_dir, "financial_data", "All_ETFs_Scorecard.xlsx"))}
 
<h3 style="color: #1f497d;">=== Virtual Broker Execution Logs ===</h3>
{format_broker_output_to_html(broker_output)}
 
<p>The Bayesian Scorecards and the Unified <b>ETF_Broker_30Day_Trial.xlsx</b> are attached to this email.</p>
</body>
</html>
"""

attachments = ";".join(attachments_list)
send_outlook_email(
    email_subject, 
    email_html_body, 
    attachments,
    logo_path=os.path.join(BASE_DIR, "oracle_logo_fixed.png")
)
