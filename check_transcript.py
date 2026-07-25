import json
import sys

sys.stdout.reconfigure(encoding='utf-8')
with open(r'C:\Users\AviShemla\.gemini\antigravity\brain\cfc7c743-b169-4b8b-a5e8-6c10348c0c51\.system_generated\logs\transcript.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        if 'success' in line.lower() and 'night' in line.lower():
            try:
                data = json.loads(line)
                if 'content' in data:
                    print(f"[{data['source']}] {data['content'][:200]}...")
            except:
                pass
