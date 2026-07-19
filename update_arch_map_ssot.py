import os
import re

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Architecture_Map.html'), 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Update the CSS class for Database
if 'classDef database' not in html:
    html = html.replace('classDef ui fill:#0d1117,stroke:#8b949e,stroke-width:3px,color:#c9d1d9,font-weight:bold;',
                        'classDef ui fill:#0d1117,stroke:#8b949e,stroke-width:3px,color:#c9d1d9,font-weight:bold;\n        classDef database fill:#0d1117,stroke:#e34c26,stroke-width:4px,color:#c9d1d9,font-weight:bold;')

# 2. Add the massive SSOT Node
if 'SSOT_DB' not in html:
    html = html.replace('        %% Orchestration',
                        '        %% The Core\n        SSOT_DB[(antigravity.db<br>4-Point SSOT Core)]:::database\n\n        %% Orchestration')

# 3. Remove deprecated output nodes
html = re.sub(r'\s*PENDING_ORDERS\[Pending_Orders.json\]:::output\s*', '\n', html)
html = re.sub(r'\s*STOCK_LEDGER\[Capital_Ledgers.csv\]:::output\s*', '\n', html)

# 4. Re-route connections to SSOT_DB
html = html.replace('STOCK_BROKER --> PENDING_ORDERS', 'STOCK_BROKER -->|Writes Pending| SSOT_DB')
html = html.replace('PENDING_ORDERS --> INTRADAY_SNIPER', 'SSOT_DB -.->|Reads Pending| INTRADAY_SNIPER')
html = html.replace('IDEMPOTENT_OVERRIDE --> STOCK_LEDGER', 'IDEMPOTENT_OVERRIDE -->|Writes Ledger| SSOT_DB')
html = html.replace('STOCK_LEDGER --> QA_BLACKLIST', 'SSOT_DB -.-> QA_BLACKLIST')
html = html.replace('STOCK_LEDGER --> BACKEND', 'SSOT_DB -->|Provides Ledger Data| BACKEND')
html = html.replace('STOCK_LEDGER --> EXEC_BRIEF', 'SSOT_DB --> EXEC_BRIEF')

# 5. Update JS JSON map for SSOT_DB
js_ssot = '"SSOT_DB": {name: "antigravity.db", purpose: "The Single Source of Truth SQLite core. Eliminates race conditions and fully decouples the Math Models, Execution Engines, and UI from fragile CSV files.", input: "Orders & Ledgers", output: "Verified States", schedule: "Always On"},'
if '"SSOT_DB"' not in html:
    html = html.replace('"MASTER":', js_ssot + '\n            "MASTER":')

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Architecture_Map.html'), 'w', encoding='utf-8') as f:
    f.write(html)

print("Architecture Map updated successfully to reflect SSOT!")
