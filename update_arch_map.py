import re

with open('C:/Users/AviShemla/AntiGravity/Architecture_Map.html', 'r', encoding='utf-8') as f:
    html = f.read()

mermaid_addition = """
    subgraph Brain[🧠 AI DeepMind Brain]
        STATE[SYSTEM_STATE.md<br/>Context & Memory]
        BLUEPRINT[Master_Blueprint.md<br/>Core Architecture]
    end
    subgraph PreFlight[🛡️ Safety Protocols]
        PREFLIGHT[preflight_check.py<br/>Zombie Process Killer]
    end

    STATE -.->|Context Memory| MASTER
    BLUEPRINT -.->|Directives| MASTER
    PREFLIGHT -->|Validates Env| MASTER
"""

js_addition = """
            "STATE": {name: "SYSTEM_STATE.md", purpose: "The dynamic memory layer of the AI assistant, tracking all crashes, recoveries, and task progress.", input: "System Events", output: "Context Memory", schedule: "Always Updated"},
            "BLUEPRINT": {name: "AntiGravity_Master_Blueprint.md", purpose: "The immutable core architectural directives for the AntiGravity system.", input: "Human Architect", output: "Core Rules", schedule: "Static"},
            "PREFLIGHT": {name: "preflight_check.py", purpose: "Diagnostic tool that scans the local Python environment for dependencies and kills zombie background processes before major pipeline executions.", input: "OS Environment", output: "Clean Execution State", schedule: "Pre-Run Hook"},
"""

if 'SYSTEM_STATE.md' not in html:
    html = html.replace('        MASTER[master_pipeline.py<br/>The Brain]', mermaid_addition + '\n        MASTER[master_pipeline.py<br/>The Brain]')
    html = html.replace('            "MASTER":', js_addition + '            "MASTER":')
    with open('C:/Users/AviShemla/AntiGravity/Architecture_Map.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print("Map updated successfully!")
else:
    print("Map is already updated.")
