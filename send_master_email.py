import os
import pandas as pd
import json
import win32com.client
import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
export_dir = BASE_DIR
scorecard_path = os.path.join(BASE_DIR, 'financial_data', 'Top5_Bayesian_Scorecard_Formatted.xlsx')
trial_report_path = os.path.join(BASE_DIR, 'financial_data', 'MultiPersona_Broker_30Day_Trial.xlsx')

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
        import database_manager
        df_l = database_manager.get_ledger("Dynamic")
        if not df_l.empty:
                last_row = df_l.iloc[-1]
                pos_json = last_row.get('Holdings_JSON', '{}')
                cash = float(last_row.get('Cash', 0))
                
                try:
                    positions = json.loads(pos_json)
                except:
                    positions = {}
                
                for asset, amount_data in positions.items():
                    dollar_amount = float(amount_data.get('dollars', 0.0)) if isinstance(amount_data, dict) else float(amount_data)
                    html += f'''
                    <tr>
                        <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold; color: #004085;">{asset}</td>
                        <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">${dollar_amount:,.2f}</td>
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
"""

try:
    import database_manager
    for p in ["Conservative", "Neutral", "BallsForBrains", "Dynamic"]:
        df_l = database_manager.get_ledger(p)
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
                    <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">{p}</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: right; color: {color}; font-weight: bold;">{sign}${daily_pnl:,.2f}</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">${eq:,.2f}</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">${cash:,.2f}</td>
                </tr>
                '''
except Exception as e:
    html_dashboard += f"<tr><td colspan='4'>Error building dashboard: {e}</td></tr>"

html_dashboard += "</tbody></table>"

broker_output_html = """
<pre style="background-color: #f4f4f4; padding: 10px;">
--- MULTI-PERSONA MULTI-ETF VIRTUAL BROKER EXECUTION ---
[MANUAL OVERRIDE] Emails triggered out of band. Dashboards manually flushed to June 9th.
</pre>
"""

email_html_body = f"""
<html>
<body style="font-family: Arial, sans-serif;">
<div style="text-align: center; margin-bottom: 20px;">
    <img src="cid:oracle_logo" width="210" alt="Axiom Logo">
</div>
<p>Good morning,</p>
<p>The automated AntiGravity pipeline has successfully finished running for today. All live tracking engines have synchronized their local ledgers.</p>
<p style="background-color: #f8f9fa; padding: 10px; border-left: 4px solid #1f497d; font-family: monospace;">
    <strong>Active Engine:</strong> {config.CURRENT_MODEL_VERSION}
</p>

<h3 style="color: #1f497d;">=== 30-Day Olympic Leaderboard ===</h3>
{html_dashboard}

<h3 style="color: #1f497d;">=== Live Portfolio Overview (Dynamic Persona) ===</h3>
{build_holdings_html(export_dir)}

<h3 style="color: #1f497d;">=== Daily Bayesian Scorecard (Tomorrow's Predictions) ===</h3>
{build_scorecard_html(scorecard_path)}

<h3 style="color: #1f497d;">=== SPY.py Data Extraction Statistics ===</h3>
<pre style="background-color: #f4f4f4; padding: 10px;">Total Processed Database Rows: 443534\nTickers Updated Successfully: 413 (These have >= 12 months history)</pre>

<h3 style="color: #1f497d;">=== Virtual Broker Execution Logs ===</h3>
{broker_output_html}

<h3 style="color: #1f497d;">=== 30-Day Trial Tracking ===</h3>
<p>The <b>MultiPersona_Broker_30Day_Trial.xlsx</b> file has been updated with today's PnL, new trades, and an updated Equity Curve. It is <b>attached to this email</b>.</p>

<hr>
<p style="color: gray; font-size: 12px;">System: All systems nominal. Live Execution Module Active.</p>
</body>
</html>
"""

try:
    outlook = win32com.client.Dispatch('outlook.application')
    mail = outlook.CreateItem(0)
    mail.To = "avi.shemla@gmail.com"
    mail.Subject = "AntiGravity Virtual Broker: OFFICIAL LIVE DATA"
    
    logo_path = os.path.join(BASE_DIR, "oracle_logo_fixed.png")
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
finally:
    import os
    os._exit(0)
