import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication
import os

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
SENDER_EMAIL = "avi.shemla@gmail.com"
SENDER_PASSWORD = "pkga yfjk rwdy rgpu"

def send_native_email(to_address, subject, html_body, attachments=None, logo_path=None):
    msg = MIMEMultipart('related')
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = to_address

    msg_alt = MIMEMultipart('alternative')
    msg.attach(msg_alt)

    msg_alt.attach(MIMEText(html_body, 'html'))

    if logo_path and os.path.exists(logo_path):
        with open(logo_path, 'rb') as f:
            img = MIMEImage(f.read())
            img.add_header('Content-ID', '<oracle_logo>')
            img.add_header('Content-Disposition', 'inline')
            msg.attach(img)

    if attachments:
        for att in attachments:
            if att and os.path.exists(att):
                with open(att, "rb") as f:
                    part = MIMEApplication(f.read(), Name=os.path.basename(att))
                part['Content-Disposition'] = f'attachment; filename="{os.path.basename(att)}"'
                msg.attach(part)

    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"Summary email successfully sent via NATIVE GMAIL to {to_address}!")
        return True
    except Exception as e:
        print(f"Failed to send email via Native Gmail. Error: {e}")
        return False

class MockPropertyAccessor:
    def __init__(self, item, path):
        self.item = item
        self.path = path
    def SetProperty(self, prop, value):
        if value == "oracle_logo":
            self.item.logo_path = self.path
            if self.path in self.item.attachments:
                self.item.attachments.remove(self.path)

class MockAttachment:
    def __init__(self, item, path):
        self.item = item
        self.path = path
        self.PropertyAccessor = MockPropertyAccessor(item, path)

class MockAttachments:
    def __init__(self, item):
        self.item = item
    def Add(self, path):
        if path not in self.item.attachments:
            self.item.attachments.append(path)
        return MockAttachment(self.item, path)

class MockMailItem:
    def __init__(self):
        self.To = ""
        self.Subject = ""
        self.HTMLBody = ""
        self.attachments = []
        self.logo_path = None
        self.Attachments = MockAttachments(self)
        self.SendUsingAccount = None
        
    def Send(self):
        send_native_email(self.To, self.Subject, self.HTMLBody, self.attachments, self.logo_path)

class MockAccount:
    SmtpAddress = "avi.shemla@gmail.com"

class MockSession:
    Accounts = [MockAccount()]

class MockOutlook:
    Session = MockSession()
    
    def CreateItem(self, code):
        return MockMailItem()
