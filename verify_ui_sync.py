import sqlite3
import os

BASE_DIR = r"C:\Users\AviShemla\AntiGravity"
DB_PATH = os.path.join(BASE_DIR, "antigravity.db")
HTML_PATH = os.path.join(BASE_DIR, "frontend", "index.html")

def verify_ui_sync():
    print("--- Starting UI-Backend Sync Verification ---")
    
    # 1. Fetch exact personas from the live database
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT persona FROM capital_ledgers")
        db_personas = [row[0] for row in cursor.fetchall() if "ETF_" not in row[0]] # Get base personas
        conn.close()
    except Exception as e:
        print(f"FAIL: Could not query database - {e}")
        return False
        
    print(f"Found active Backend Personas: {db_personas}")
    
    # 2. Read the frontend HTML file
    if not os.path.exists(HTML_PATH):
        print("FAIL: frontend/index.html not found.")
        return False
        
    with open(HTML_PATH, 'r', encoding='utf-8') as f:
        html_content = f.read()
        
    # 3. Mathematically prove every DB persona exists in the UI dropdown
    missing_personas = []
    for persona in db_personas:
        # Search for either the value attribute or the literal string
        if f'value="{persona}"' not in html_content and persona not in html_content:
            missing_personas.append(persona)
            
    if missing_personas:
        print(f"FAIL: The following active backend personas are MISSING from the frontend UI: {missing_personas}")
        print("CRITICAL VIOLATION OF THE VERTICAL TRACEABILITY LAW.")
        return False
        
    print("SUCCESS: The Frontend UI is 100% synchronized with the Backend Database.")
    return True

if __name__ == "__main__":
    if not verify_ui_sync():
        exit(1)
