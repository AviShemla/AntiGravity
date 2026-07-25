import subprocess
import time
import os
import sys

print("Starting ETF Broker via subprocess...")
proc = subprocess.Popen(
    [sys.executable, 'etf_virtual_broker.py', '--target-date', '2026-07-22'],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

start = time.time()
while time.time() - start < 120:
    # We don't read stdout continuously because it might block if no output.
    # We just poll.
    if proc.poll() is not None:
        print("Process exited naturally.")
        break
    time.sleep(1)

if proc.poll() is None:
    print("Forcefully killing the deadlocked ETF broker process after 120 seconds!")
    proc.terminate()
    proc.kill()
    
out, err = proc.communicate()
print("STDOUT:")
print(out)
print("STDERR:")
print(err)

print("Done generating pending orders.")
