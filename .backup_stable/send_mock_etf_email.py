import os
import pandas as pd
import json
import win32com.client

BASE_DIR = r'C:\Users\AviShemla\AntiGravity'
export_dir = BASE_DIR
scorecard_path = os.path.join(BASE_DIR, 'financial_data', 'All_ETFs_Scorecard.xlsx')
trial_report_path = os.path.join(BASE_DIR, 'financial_data', 'ETF_Broker_30Day_Trial.xlsx')
TARGET_ETFS = ["XLK", "XLV", "XLY", "XLF"]

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

def build_scorecard_html(scorecard_path):
    html = """
    <table style="width:100%; border-collapse: collapse; font-family: Arial, sans-serif; margin-bottom: 20px; font-size: 14px;">
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
            df = pd.read_excel(scorecard_path)
            for _, row in df.iterrows():
                pup_color = "green" if row['P(UP)'] > 0.5 else "red"
                html += f'''
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">{row.get('Ticker', '')}</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center; color: {pup_color}; font-weight: bold;">{row.get('P(UP)', 0)*100:.1f}%</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{row.get('Expected Return %', 0)*100:.2f}%</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{row.get('Volatility %', 0)*100:.2f}%</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: center; font-weight: bold;">{row.get('Kelly Sizing', 0)*100:.1f}%</td>
                </tr>
                '''
    except Exception as e:
         html += f"<tr><td colspan='5'>Error loading scorecard: {e}</td></tr>"
         
    html += "</tbody></table>"
    return html

html_dashboard = """
    <table style="width:100%; border-collapse: collapse; font-family: Arial, sans-serif; margin-bottom: 20px; font-size: 14px;">
        <thead>
            <tr style="background-color: #1f497d; color: white;">
                <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Persona</th>
                <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Day's PnL ($)</th>
                <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Total Equity ($)</th>
                <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Available Cash ($)</th>
            </tr>
        </thead>
        <tbody>
            <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Conservative</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right; color: green; font-weight: bold;">$0.00</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right;">$10,067.82</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right;">$10,067.82</td></tr>
            <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Neutral</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right; color: green; font-weight: bold;">$0.00</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right;">$10,083.34</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right;">$10,083.34</td></tr>
            <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">BallsForBrains</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right; color: green; font-weight: bold;">$0.00</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right;">$10,228.22</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right;">$10,228.22</td></tr>
            <tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Dynamic</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right; color: green; font-weight: bold;">$0.00</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right;">$10,000.00</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right;">$10,000.00</td></tr>
        </tbody>
    </table>
"""

broker_output_html = """
<pre style="background-color: #f4f4f4; padding: 10px;">
--- MULTI-PERSONA MULTI-ETF VIRTUAL BROKER EXECUTION ---

--- Persona: CONSERVATIVE ---
[SAFETY STOP] Broker already executed for date 2026-06-02.
--- Persona: NEUTRAL ---
[SAFETY STOP] Broker already executed for date 2026-06-02.
--- Persona: BALLSFORBRAINS ---
[SAFETY STOP] Broker already executed for date 2026-06-02.
--- Persona: DYNAMIC ---
[SAFETY STOP] Broker already executed for date 2026-06-02.
--- LIVE ETF LEADERBOARD ---
#1 BallsForBrains : $10,228.22  (Profit: +$228.22)
#2 Neutral        : $10,083.34  (Profit: +$83.34)
#3 Conservative   : $10,067.82  (Profit: +$67.82)
#4 Dynamic        : $10,000.00  (Profit: +$0.00)
</pre>
"""

email_html_body = f"""
<html>
<body style="font-family: Arial, sans-serif;">
<div style="text-align: center; margin-bottom: 20px;">
    <img src="cid:oracle_logo" width="210" alt="Axiom Logo">
</div>
<p>Good morning,</p>
<p>The specialized ETF Hybrid pipeline has successfully finished running for <b>{', '.join(TARGET_ETFS)}</b>. (THIS IS A TEST RENDER)</p>

<h3 style="color: #1f497d;">=== 30-Day ETF Olympic Leaderboard ===</h3>
{html_dashboard}

<h3 style="color: #1f497d;">=== Live Portfolio Overview (Dynamic Persona) ===</h3>
{build_holdings_html(export_dir)}

<h3 style="color: #1f497d;">=== Daily Bayesian Scorecard (Tomorrow's ETF Predictions) ===</h3>
{build_scorecard_html(os.path.join(export_dir, "financial_data", "All_ETFs_Scorecard.xlsx"))}

<h3 style="color: #1f497d;">=== Virtual Broker Execution Logs ===</h3>
{broker_output_html}

<p>The Bayesian Scorecards and the Unified <b>ETF_Broker_30Day_Trial.xlsx</b> are attached to this email.</p>
</body>
</html>
"""

try:
    outlook = win32com.client.Dispatch('outlook.application')
    mail = outlook.CreateItem(0)
    mail.To = "avi.shemla@gmail.com"
    mail.Subject = "AntiGravity ETF Broker: Multi-ETF Performance (TEST RENDER)"
    
    logo_path = os.path.join(BASE_DIR, "oracle_logo.png")
    if os.path.exists(logo_path):
        attachment = mail.Attachments.Add(logo_path)
        attachment.PropertyAccessor.SetProperty("http://schemas.microsoft.com/mapi/proptag/0x3712001E", "oracle_logo")
        
    mail.HTMLBody = email_html_body
    
    if os.path.exists(scorecard_path):
        mail.Attachments.Add(scorecard_path)
    if os.path.exists(trial_report_path):
        mail.Attachments.Add(trial_report_path)
        
    mail.Send()
    print("Test HTML Render Sent Successfully!")
except Exception as e:
    print(f"Failed to send email. Error: {e}")
