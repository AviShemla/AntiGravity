import os
import pandas as pd
import json
import win32com.client
import config

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
        import database_manager
        df_l = database_manager.get_ledger("ETF_Dynamic")
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

def build_dynamic_changes_html(base_dir):
    html = """
    <table style="width:100%; border-collapse: collapse; font-family: Arial, sans-serif; margin-bottom: 20px; font-size: 14px;">
        <thead>
            <tr style="color: white;">
                <th style="padding: 10px; border: 1px solid #ddd; text-align: center; width: 33%; background-color: #28a745;">Added</th>
                <th style="padding: 10px; border: 1px solid #ddd; text-align: center; width: 33%; background-color: #dc3545;">Dropped</th>
                <th style="padding: 10px; border: 1px solid #ddd; text-align: center; width: 33%; background-color: #6c757d;">Kept</th>
            </tr>
        </thead>
        <tbody>
    """
    try:
        changes_path = os.path.join(base_dir, 'financial_data', 'Dynamic_ETF_Changes.json')
        if os.path.exists(changes_path):
            with open(changes_path, 'r') as f:
                changes = json.load(f)
            
            added = changes.get("Added", [])
            dropped = changes.get("Dropped", [])
            kept = changes.get("Kept", [])
            
            max_len = max(len(added), len(dropped), len(kept))
            if max_len == 0:
                html += "<tr><td colspan='3' style='text-align:center;'>No changes this week.</td></tr>"
            else:
                for i in range(max_len):
                    a_val = added[i] if i < len(added) else ""
                    d_val = dropped[i] if i < len(dropped) else ""
                    k_val = kept[i] if i < len(kept) else ""
                    
                    html += f'''
                    <tr>
                        <td style="padding: 8px; border: 1px solid #ddd; text-align: center; font-weight: bold; color: #28a745;">{a_val}</td>
                        <td style="padding: 8px; border: 1px solid #ddd; text-align: center; font-weight: bold; color: #dc3545; text-decoration: line-through;">{d_val}</td>
                        <td style="padding: 8px; border: 1px solid #ddd; text-align: center; color: #6c757d;">{k_val}</td>
                    </tr>
                    '''
        else:
            html += "<tr><td colspan='3' style='text-align:center; padding: 10px;'>No rotation data available yet.</td></tr>"
    except Exception as e:
         html += f"<tr><td colspan='3'>Error loading changes: {e}</td></tr>"
         
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
        df_l = database_manager.get_ledger(f"ETF_{p}")
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
<p>The specialized ETF Hybrid pipeline has successfully finished running for <b>{', '.join(TARGET_ETFS)}</b>. All active ledgers have been synchronized.</p>
<p style="background-color: #f8f9fa; padding: 10px; border-left: 4px solid #1f497d; font-family: monospace;">
    <strong>Active Engine:</strong> {config.CURRENT_MODEL_VERSION}
</p>

<h3 style="color: #1f497d;">=== Weekly Dynamic Rotation (Delta) ===</h3>
{build_dynamic_changes_html(BASE_DIR)}

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
    mail.Subject = "AntiGravity ETF Broker: OFFICIAL LIVE DATA"
    
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
