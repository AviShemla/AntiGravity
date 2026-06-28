import win32com.client
import re
import sys

def send_notification(subject, body):
    email = "avi.shemla@gmail.com"
        
    try:
        outlook = win32com.client.Dispatch('outlook.application')
        mail = outlook.CreateItem(0)
        mail.To = email
        mail.Subject = subject
        mail.Body = body
        mail.Send()
        print(f"Email sent successfully to {email}!")
    except Exception as e:
        print(f"Failed to send email. Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 2:
        subject = sys.argv[1]
        body = sys.argv[2]
        send_notification(subject, body)
