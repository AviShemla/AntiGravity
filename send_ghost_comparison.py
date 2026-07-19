import win32com.client
import os
import sys
import datetime

def send_ghost_comparison():
    email = "avi.shemla@gmail.com"
    subject = "🔬 EXPERIMENTAL: TNX Macro Model A/B Test"
    
    body = """
    === ANTI-GRAVITY A/B TEST: GHOST PIPELINE ===
    
    The live trades for today were executed using the classic, stable Bayesian models.
    However, the Ghost Pipeline has just finished running a parallel simulation using the new 10-Year Treasury Yield (TNX) macro indicators.
    
    Attached is the TNX_Test_Scorecard.xlsx. 
    
    Open this side-by-side with your standard Top5_Bayesian_Scorecard_Formatted.xlsx to see exactly how the interest rate features dynamically altered the P(UP) probabilities and 'Buy/Hold/Sell' recommendations!
    
    (Note: No real trades were executed based on this experimental scorecard).
    """
    
    attachment_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'TNX_Test_Scorecard.xlsx')
    
    try:
        outlook = win32com.client.Dispatch('outlook.application')
        mail = outlook.CreateItem(0)
        mail.To = email
        mail.Subject = subject
        mail.Body = body
        
        if os.path.exists(attachment_path):
            mail.Attachments.Add(attachment_path)
            print(f"Attached {attachment_path}")
        else:
            print(f"WARNING: Attachment not found at {attachment_path}")
            
        mail.Send()
        print(f"Experimental Ghost email sent successfully to {email}!")
    except Exception as e:
        print(f"Failed to send experimental email. Error: {e}")

if __name__ == "__main__":
    send_ghost_comparison()
