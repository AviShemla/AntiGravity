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
    
    BASE_DIR = r'C:\Users\AviShemla\AntiGravity'
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
        os._exit(0)
        
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
        
        for account in outlook.Session.Accounts:
            if "gmail.com" in account.SmtpAddress.lower():
                mail.SendUsingAccount = account
                break
                
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

if __name__ == '__main__':
    import laptop_catchup_controller
    laptop_catchup_controller.catchup_etf_pipeline()

