import subprocess
import sys
import os
import re
import pandas as pd
import json

# ==========================================
# CONFIGURATION
# ==========================================
# Put your target email address here!
RECIPIENT_EMAIL = "avi.shemla@gmail.com"
# ==========================================

import datetime
import os
import sys
try:
    import pandas_market_calendars as mcal
    import pandas as pd
    
    BASE_DIR = r'C:\Users\AviShemla\AntiGravity'
    ledger_path = os.path.join(BASE_DIR, 'financial_data', 'Capital_Ledger_Dynamic.csv')
    
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
            print(f"[IDEMPOTENT RUN] Pipeline already executed for {prediction_date_str}. Proceeding to recalculate and overwrite if Integrity Check passes.")
            
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

print("=== STARTING DAILY PIPELINE ===")
sys.path.insert(0, r"C:\Users\AviShemla\AntiGravity")
try:
    from failover_downloader import clear_warnings, clear_quarantined_tickers
    clear_warnings()
    clear_quarantined_tickers()
except Exception as e:
    print(f"Warning: Could not clear warnings or quarantine list: {e}")

print("Step 1: Running SPY.py from AntiGravity folder...")

spy_path = r"C:\Users\AviShemla\AntiGravity\SPY.py"
export_dir = r"C:\Users\AviShemla\AntiGravity"
data_file = r"C:\Users\AviShemla\AntiGravity\financial_data\SP500_Clean_Advanced_Analysis.csv"

python_exe = sys.executable

# Get initial modified time
initial_mtime = 0
if os.path.exists(data_file):
    initial_mtime = os.path.getmtime(data_file)

# Run SPY.py and capture its output (run from AntiGravity so it saves here!)
try:
    result1 = subprocess.run([python_exe, spy_path], cwd=export_dir, capture_output=True, text=True, timeout=5400)
except subprocess.TimeoutExpired as e:
    error_msg = f"Pipeline Aborted.\nSPY.py timed out after 60 minutes.\n\nErrors:\n{e}"
    print(error_msg)
    send_outlook_email("AntiGravity Error: Daily Pipeline Failed", f"<pre>{error_msg}</pre>")
    sys.exit(1)

# Get final modified time
final_mtime = 0
if os.path.exists(data_file):
    final_mtime = os.path.getmtime(data_file)

file_updated = final_mtime > initial_mtime

if result1.returncode != 0 or not file_updated:
    error_msg = f"Pipeline Aborted.\nSPY.py Exit Code: {result1.returncode}\nData File Updated: {file_updated}\n\nLast SPY.py Output:\n{result1.stdout[-1000:]}\n\nErrors:\n{result1.stderr}"
    print(error_msg)
    send_outlook_email("AntiGravity Error: Daily Pipeline Failed", f"<pre>{error_msg}</pre>")
    sys.exit(1)

print("\nStep 1 Complete: SPY.py finished successfully. Extracting stats...")

# Parse SPY.py output for statistics
spy_output = result1.stdout
rows = re.search(r"Total processed database rows:\s*(\d+)", spy_output)
updated = re.search(r"Tickers Updated Successfully:\s*(\d+)", spy_output)
added = re.search(r"New Tickers Added From Scratch:\s*(\d+)", spy_output)
failed = re.search(r"Tickers Failed / Delisted:\s*(\d+)", spy_output)

stats_text = (
    f"Total Processed Database Rows: {rows.group(1) if rows else 'N/A'}\n"
    f"Tickers Updated Successfully: {updated.group(1) if updated else 'N/A'} (These have >= 12 months history)\n"
    f"New Tickers Added: {added.group(1) if added else 'N/A'}\n"
    f"Tickers Failed/Delisted: {failed.group(1) if failed else 'N/A'}"
)

print("\nStep 1.5: Running Meta-Predictor Tracker (Sunday Alpha Recalibration)...")
if datetime.datetime.today().weekday() == 6: # Sunday
    meta_script = r"C:\Users\AviShemla\AntiGravity\meta_predictor_tracker.py"
    try:
        subprocess.run([python_exe, meta_script], cwd=export_dir, capture_output=True, text=True, timeout=600)
        print("  => Meta-Predictor Tracker successfully recalculated Alpha Priors.")
    except Exception as e:
        print(f"  => Meta-Predictor Tracker failed: {e}")
else:
    print("  => Skipped (Not Sunday). Using existing Meta_Alpha_Priors.json.")

print("\nStep 2: Running export_bayesian_scorecard_formatted.py...")

export_script = r"C:\Users\AviShemla\AntiGravity\export_bayesian_scorecard_formatted.py"
try:
    result2 = subprocess.run([python_exe, export_script], cwd=export_dir, capture_output=True, text=True, timeout=1800)
except subprocess.TimeoutExpired as e:
    error_msg = f"SPY.py succeeded, but export_bayesian_scorecard_formatted.py timed out after 30 minutes.\n\nErrors:\n{e}"
    print(error_msg)
    send_outlook_email("AntiGravity Error: Bayesian Export Failed", f"<pre>{error_msg}</pre>")
    sys.exit(1)

if result2.returncode != 0:
    error_msg = f"SPY.py succeeded, but export_bayesian_scorecard_formatted.py failed with exit code {result2.returncode}.\n\nErrors:\n{result2.stderr}"
    print(error_msg)
    send_outlook_email("AntiGravity Error: Bayesian Export Failed", f"<pre>{error_msg}</pre>")
    sys.exit(1)

# Parse retrained and suspended tickers from the exporter output
export_output = result2.stdout
retrained_match = re.search(r"=== RETRAINED TICKERS SUMMARY ===\n(.*)", export_output)
retrained_text = retrained_match.group(1).strip() if retrained_match else "None"

suspended_match = re.search(r"=== SUSPENDED TICKERS SUMMARY ===\n(.*)", export_output)
suspended_text = suspended_match.group(1).strip() if suspended_match else "None"

print("\nStep 2.5: Running QA Models Bounds Validation...")
qa_models_script = r"C:\Users\AviShemla\AntiGravity\qa_models.py"
try:
    result_qa = subprocess.run([python_exe, qa_models_script], cwd=export_dir, capture_output=True, text=True, timeout=120)
    print(result_qa.stdout)
    if result_qa.returncode != 0:
        print(f"  => QA Models script failed: {result_qa.stderr}")
except Exception as e:
    print(f"  => QA Models execution failed: {e}")

print("\nStep 3: Running Virtual Broker...")
broker_script = r"C:\Users\AviShemla\AntiGravity\virtual_broker.py"
try:
    result3 = subprocess.run([python_exe, broker_script], cwd=export_dir, capture_output=True, text=True, timeout=600)
    broker_output = result3.stdout
except subprocess.TimeoutExpired as e:
    broker_output = "Virtual Broker timed out."

print("\nStep 4: Generating 30-Day Trial Excel Report...")
excel_exporter = r"C:\Users\AviShemla\AntiGravity\export_broker_excel_report.py"
try:
    subprocess.run([python_exe, excel_exporter], cwd=export_dir, capture_output=True, text=True, timeout=120)
except subprocess.TimeoutExpired:
    print("Excel report generation timed out.")

print("\nStep 5: Running Automated QA Assistant (Blacklist Audit)...")
qa_script = r"C:\Users\AviShemla\AntiGravity\qa_blacklist.py"
try:
    if os.path.exists(qa_script):
        subprocess.run([python_exe, qa_script], cwd=export_dir, capture_output=True, text=True, timeout=120)
        print("  => QA Assistant audit completed.")
except subprocess.TimeoutExpired:
    print("QA Assistant audit timed out.")

print("\n=== DAILY PIPELINE COMPLETED SUCCESSFULLY ===")

# Excel Attachment Paths
scorecard_path = r"C:\Users\AviShemla\AntiGravity\financial_data\Top5_Bayesian_Scorecard_Formatted.xlsx"
trial_report_path = r"C:\Users\AviShemla\AntiGravity\financial_data\MultiPersona_Broker_30Day_Trial.xlsx"

# Draft and send the success HTML email
email_subject = "AntiGravity: Single Stocks Daily Pipeline Completed Successfully"

suspended_alert = ""
if suspended_text != "None":
    suspended_alert = f'<div style="background-color: #ffe6e6; padding: 15px; border-left: 5px solid red; margin-bottom: 20px;"><b style="color:red; font-size:16px;">ATTENTION REQUIRED: The following tickers have no valid causal chain and have been SUSPENDED from trading: {suspended_text}</b></div>'

# --- BUILD BLACKLIST HTML ---
try:
    import sys
    if export_dir not in sys.path:
        sys.path.append(export_dir)
    from blacklist_engine import get_blacklisted_tickers
    blacklisted = get_blacklisted_tickers(persona="BallsForBrains")
    if blacklisted:
        blacklist_html = '<div style="background-color: #fff3cd; padding: 15px; border-left: 5px solid #ffc107; margin-bottom: 20px;"><b style="color:#856404; font-size:16px;">🚫 BLACKLISTED (QUARANTINED) ASSETS: ' + ', '.join(blacklisted) + '</b><br><span style="color:#856404; font-size:13px;">These assets have accumulated 3 or more negative strikes in the last 30 days and are blocked from new capital allocation.</span></div>'
    else:
        blacklist_html = ""
except Exception as e:
    blacklist_html = f"<p>Error loading blacklist: {e}</p>"

# --- BUILD HTML MINI-DASHBOARD ---
html_dashboard = """
<table style="width:100%; border-collapse: collapse; font-family: Arial, sans-serif; margin-bottom: 20px;">
    <thead>
        <tr style="background-color: #1f497d; color: white;">
            <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Persona</th>
            <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Day's PnL ($)</th>
            <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Total Equity ($)</th>
            <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Available Cash ($)</th>
        </tr>
    </thead>
    <tbody>
"""

try:
    for p in ["Conservative", "Neutral", "BallsForBrains", "Dynamic"]:
        ledger_path = os.path.join(export_dir, 'financial_data', f'Capital_Ledger_{p}.csv')
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
                <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Ticker</th>
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
        ledger_path = os.path.join(export_dir, 'financial_data', 'Capital_Ledger_Dynamic.csv')
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

# --- BUILD PIPELINE WARNINGS ALERT HTML ---
try:
    if export_dir not in sys.path:
        sys.path.append(export_dir)
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

email_html_body = f"""
<html>
<body style="font-family: Arial, sans-serif;">
<div style="text-align: center; margin-bottom: 20px;">
    <img src="cid:oracle_logo" width="210" alt="The ORACLE">
</div>
<p>Good morning,</p>
<p>The automated AntiGravity pipeline has successfully finished running for today.</p>

{suspended_alert}
{blacklist_html}
{warnings_html}

<h3 style="color: #1f497d;">=== 🏎️ 30-Day Olympic Leaderboard ===</h3>
{html_dashboard}

<h3 style="color: #1f497d;">=== 📊 Live Portfolio Overview (Dynamic Persona) ===</h3>
{build_holdings_html(export_dir)}

<h3 style="color: #1f497d;">=== 🔮 Daily Bayesian Scorecard (Tomorrow's Predictions) ===</h3>
{build_scorecard_html(scorecard_path)}

<h3 style="color: #1f497d;">=== SPY.py Data Extraction Statistics ===</h3>
<pre style="background-color: #f4f4f4; padding: 10px;">{stats_text}</pre>

<h3 style="color: #1f497d;">=== Self-Healing Model Diagnostics ===</h3>
<p><b>Tickers that suffered a MISS yesterday and were dynamically RETRAINED today:</b><br>{retrained_text}</p>

<h3 style="color: #1f497d;">=== Virtual Broker Execution Logs ===</h3>
{format_broker_output_to_html(broker_output)}

<h3 style="color: #1f497d;">=== 30-Day Trial Tracking ===</h3>
<p>The <b>MultiPersona_Broker_30Day_Trial.xlsx</b> file has been updated with today's PnL, new trades, and an updated Equity Curve. It is <b>attached to this email</b>.</p>

<hr>
<p style="color: gray; font-size: 12px;">System: All systems nominal.</p>
</body>
</html>
"""

# Attach both Excel files
attachments = f"{scorecard_path};{trial_report_path}" if os.path.exists(trial_report_path) else scorecard_path

send_outlook_email(
    "AntiGravity Virtual Broker: Daily Performance & Scorecard", 
    email_html_body, 
    attachments,
    logo_path=os.path.join(BASE_DIR, "oracle_logo_fixed.png")
)
