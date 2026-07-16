import urllib.request
import time
import sys

print("Polling API to confirm Uvicorn is online...")
for i in range(10):
    try:
        data = urllib.request.urlopen('http://127.0.0.1/api/stats', timeout=3).read().decode()
        print(f"SUCCESS! API Response preview: {data[:150]}")
        sys.exit(0)
    except Exception as e:
        print(f"Attempt {i+1} failed: {e}")
        time.sleep(1)

print("CRITICAL FAILURE: Uvicorn did not boot up after 10 seconds.")
sys.exit(1)
