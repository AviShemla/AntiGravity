import win32com.client
import os
import markdown

recipient = "avi.shemla@gmail.com"
subject = "AntiGravity: New Laptop Migration Protocol & Instructions"

# Read the Walkthrough artifact
walkthrough_path = r"C:\Users\AviShemla\.gemini\antigravity\brain\b409853a-2b0b-46f6-a175-a22b0cfe3421\walkthrough.md"
with open(walkthrough_path, "r", encoding="utf-8") as f:
    md_content = f.read()

# Convert to HTML for the email
html_body = f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #2c3e50;">Automated Migration Assistant</h2>
    {markdown.markdown(md_content)}
    <hr>
    <p><i>This is an automated transmission from your AntiGravity AI. Safe travels to the new machine!</i></p>
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
            
    mail.To = recipient
    mail.Subject = subject
    mail.HTMLBody = html_body
    
    # Attach the scripts
    bat_script = r"C:\Users\AviShemla\AntiGravity\Setup_New_Laptop.bat"
    req_script = r"C:\Users\AviShemla\AntiGravity\requirements.txt"
    
    # Outlook blocks .bat files, so we copy it to .txt for the attachment
    safe_bat_script = r"C:\Users\AviShemla\AntiGravity\Setup_New_Laptop.txt"
    if os.path.exists(bat_script):
        import shutil
        shutil.copy(bat_script, safe_bat_script)
        mail.Attachments.Add(safe_bat_script)
        
    if os.path.exists(req_script):
        mail.Attachments.Add(req_script)
    
    mail.Send()
    print(f"Successfully sent migration instructions to {recipient}")
except Exception as e:
    print(f"Failed to send email: {e}")
