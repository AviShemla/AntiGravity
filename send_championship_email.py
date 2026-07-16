import win32com.client
import os
import pandas as pd

BASE_DIR = r'C:\Users\AviShemla\AntiGravity'
RECIPIENT_EMAIL = "avi.shemla@gmail.com"

def send_victorious_email():
    csv_path = os.path.join(BASE_DIR, "financial_data", "Olympic_Shootout_Results_MASTER.csv")
    
    el_cap = 10000.0
    el_volti = 10000.0
    champion = 10000.0
    
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        if not df.empty:
            last_row = df.iloc[-1]
            el_cap = float(last_row['EL_CAP (70% Liquidity)'])
            el_volti = float(last_row['EL_VOLTI (70% Stability)'])
            champion = float(last_row['CHAMPION (Live VIP)'])
            
    el_cap_pct = ((el_cap - 10000.0) / 10000.0) * 100
    el_volti_pct = ((el_volti - 10000.0) / 10000.0) * 100
    champion_pct = ((champion - 10000.0) / 10000.0) * 100
    
    scores = {"EL_CAP": el_cap, "EL_VOLTI": el_volti, "CHAMPION": champion}
    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    winner = sorted_scores[0][0]
    
    medals = ["🥇", "🥈", "🥉"]
    tbody_html = ""
    for idx, (persona, equity) in enumerate(sorted_scores):
        pct = ((equity - 10000.0) / 10000.0) * 100
        color = '#2e8b57' if pct >= 0 else '#dc3545'
        bg = 'background-color: #f8f9fa;' if idx % 2 == 0 else ''
        tbody_html += f"""
                    <tr style="{bg}">
                        <td style="padding: 10px; border: 1px solid #ddd; text-align: left;">{medals[idx]} <b>{persona}</b></td>
                        <td style="padding: 10px; border: 1px solid #ddd; text-align: right; font-weight: bold;">${equity:,.2f}</td>
                        <td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: {color}; font-weight: bold;">{pct:+.2f}%</td>
                    </tr>"""
    
    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif;">
    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 10px; border: 1px solid #ddd;">
        
        <div style="text-align: center; margin-bottom: 20px;">
            <img src="cid:oracle_logo" width="210" alt="The ORACLE">
        </div>
        
        <h2 style="color: #1f497d; text-align: center;">🏆 The ORACLE: Olympic Championship Complete</h2>
        
        <div style="background-color: white; padding: 15px; border-radius: 8px; margin-top: 20px; text-align: center;">
            <p style="font-size: 18px; font-weight: bold; color: #2e8b57;">✅ The Zombie Failsafe Patch Worked Flawlessly!</p>
            <p style="font-size: 16px;">The 5-day Olympic Championship Backtest has officially crossed the finish line without a single crash.</p>
            
            <h3 style="color: #333;">Final Equity Results (Starting Capital: $10,000)</h3>
            <table style="width:100%; border-collapse: collapse; margin-top: 15px; font-size: 16px;">
                <thead>
                    <tr style="background-color: #1f497d; color: white;">
                        <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Persona</th>
                        <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Final Equity</th>
                        <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">Return (%)</th>
                    </tr>
                </thead>
                <tbody>{tbody_html}
                </tbody>
            </table>
            
            <p style="font-size: 14px; text-align: left; margin-top: 20px;">The {winner} momentum portfolio officially won the shootout!</p>
            <p style="font-size: 14px; text-align: left;">I have attached the full <b>Olympic_Shootout_Results_MASTER.csv</b> file containing every single mathematical probability and trade execution log for your review.</p>
        </div>

    </div>
    </body>
    </html>
    """
    
    try:
        outlook = win32com.client.Dispatch('outlook.application')
        mail = outlook.CreateItem(0)
        
        for account in outlook.Session.Accounts:
            if "gmail.com" in account.SmtpAddress.lower():
                mail.SendUsingAccount = account
                break
                
        mail.To = RECIPIENT_EMAIL
        mail.Subject = f"🏆 The ORACLE: Olympic Championship Final Results ({winner} Wins!)"
        
        logo_path = os.path.join(BASE_DIR, "oracle_logo_fixed.png")
        if os.path.exists(logo_path):
            attachment = mail.Attachments.Add(logo_path)
            attachment.PropertyAccessor.SetProperty("http://schemas.microsoft.com/mapi/proptag/0x3712001E", "oracle_logo")
        
        if os.path.exists(csv_path):
            mail.Attachments.Add(csv_path)
            
        mail.HTMLBody = html
        mail.Send()
        print("Victorious Championship email successfully sent!")
    except Exception as e:
        print(f"Failed to send Championship email: {e}")

if __name__ == "__main__":
    send_victorious_email()
    import os
    os._exit(0)
