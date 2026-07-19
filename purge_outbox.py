
import win32com.client
import sys

try:
    outlook = win32com.client.Dispatch('outlook.application')
    mapi = outlook.GetNamespace('MAPI')
    outbox = mapi.GetDefaultFolder(4) # 4 is Outbox
    
    items = outbox.Items
    deleted = 0
    
    # Iterate backwards when deleting
    for i in range(items.Count, 0, -1):
        item = items.Item(i)
        if 'AntiGravity QA Alert' in item.Subject:
            item.Delete()
            deleted += 1
            
    print(f'Purged {deleted} stuck emails from Outlook Outbox.')
except Exception as e:
    print(f'Error: {e}')

