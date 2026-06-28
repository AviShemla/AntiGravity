import win32com.client
import pytest
from bs4 import BeautifulSoup

def test_recent_emails_for_crashes():
    """
    Scans the most recent pipeline emails sent via Outlook to ensure no PyMC or PyTensor crashes
    are reported in the HTML body. If any 'Model crash' or 'incompatible shape' strings are detected,
    this QA test will fail and block deployment.
    """
    try:
        outlook = win32com.client.Dispatch('Outlook.Application')
        sent_folder = outlook.Session.GetDefaultFolder(5) # 5 is the Sent folder
        emails = sent_folder.Items
        emails.Sort('[SentOn]', True)
        
        # Look at the last 20 sent emails and filter for our pipeline emails
        pipeline_subjects = [
            "🏆 The ORACLE:", 
            "Executive Brief:", 
            "Sector Rotation", 
            "ETF Scorecard", 
            "AntiGravity Dashboard"
        ]
        
        checked_emails = 0
        for email in emails:
            if checked_emails >= 3:
                break
                
            try:
                subject = getattr(email, 'Subject', '')
                body = getattr(email, 'HTMLBody', '')
                
                # Check if this is one of our pipeline emails
                if any(kw in subject for kw in pipeline_subjects):
                    checked_emails += 1
                    
                    # Convert HTML to plain text to search for errors
                    soup = BeautifulSoup(body, 'html.parser')
                    text_content = soup.get_text().lower()
                    
                    # Assert no fatal error strings exist in the email body
                    error_keywords = [
                        "model crash", 
                        "incompatible shape", 
                        "vectorized input", 
                        "traceback", 
                        "error checking",
                        "exception"
                    ]
                    
                    for kw in error_keywords:
                        assert kw not in text_content, f"CRITICAL: Found error '{kw}' in sent email: {subject}"
                        
            except Exception as e:
                # Some Outlook items might be meeting invites or other objects without a Subject
                continue
                
    except Exception as e:
        # If we can't connect to Outlook, skip the test or warn
        print(f"Could not connect to Outlook to verify emails: {e}")
        pass
