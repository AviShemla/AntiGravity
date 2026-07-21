import re

with open('frontend/Architecture_Map.html', 'r', encoding='utf-8') as f:
    text = f.read()

mermaid_graph = """    graph TD
        %% Inputs
        classDef input fill:#0d1117,stroke:#1f6feb,stroke-width:3px,color:#c9d1d9;
        classDef pipeline fill:#0d1117,stroke:#d29922,stroke-width:3px,color:#c9d1d9;
        classDef model fill:#0d1117,stroke:#238636,stroke-width:3px,color:#c9d1d9;
        classDef output fill:#0d1117,stroke:#f85149,stroke-width:3px,color:#c9d1d9;
        classDef broker fill:#0d1117,stroke:#a371f7,stroke-width:3px,color:#c9d1d9;
        classDef ui fill:#0d1117,stroke:#8b949e,stroke-width:3px,color:#c9d1d9;
        classDef database fill:#0d1117,stroke:#e34c26,stroke-width:4px,color:#c9d1d9;
        classDef script fill:#0d1117,stroke:#ff69b4,stroke-width:3px,color:#c9d1d9;

        %% Data Sources
        YF["Yahoo Finance<br>Price Data"]:::input
        TIINGO["Tiingo Institutional<br>API Fallback"]:::input
        FAILOVER["failover_downloader.py<br>Self-Healing API"]:::pipeline
        FRED["FRED<br>Macro Data"]:::input
        VIX["VIX Monitor<br>Fear Gauge"]:::input

        %% Connections
        YF --> FAILOVER
        TIINGO --> FAILOVER

        %% The Core
        SSOT_DB["antigravity.db<br>4-Point SSOT Core"]:::database

        %% Orchestration
        ENGINE_CONFIG["engine_config.py<br>PyTensor C-Graph Injector"]:::pipeline
        MASTER["master_pipeline.py<br>Orchestrator"]:::pipeline
        
        %% Stock Pipeline
        subgraph Daily Stock Universe
            STOCK_SCREEN["fast_screener.py<br>Top 15 Momentum"]:::pipeline
            DATA_LOADER["data_loader.py<br>Matrix Array Validation"]:::pipeline
            STOCK_PYMC["export_bayesian_scorecard.py<br>Apollo Causality Engine"]:::model
            YIELD_CURVE["TNX Yield Curve<br>Risk Sensor"]:::model
            QA_MODELS["qa_models.py<br>Bounds Validator"]:::model
            SECTOR_GRAVITY["sector_gravity.py<br>Macro Momentum Filter"]:::pipeline
            STOCK_BROKER["virtual_broker.py<br>3-Persona Staging"]:::broker
            INTRADAY_SNIPER["intraday_tracker.py<br>Intraday Execution Engine"]:::broker
            STOCK_SCORE["Top5_Scorecard.xlsx"]:::output
            QA_BLACKLIST["qa_blacklist.py<br>Blacklist Auditor"]:::pipeline
            IDEMPOTENT_OVERRIDE["Idempotent Integrity<br>Ledger Overwrite"]:::model
        end

        %% The Bridge
        subgraph The Weekend Bridge
            FUNDAMENTALS["extract_fundamentals.py<br>SP 500 Fundamentals"]:::model
            STOCK_DB["SP 500<br>Fundamental Database"]:::input
            SUNDAY_SCREENER["ETF_Universe_Screener.py<br>Nasdaq FTP 50M Liquidity Scan"]:::pipeline
            MASTER_ETF_JSON["Master_ETF_Universe.json<br>Top 35 Menu"]:::input
        end

        %% ETF Pipeline
        subgraph Dynamic Thematic ETF Universe
            ETF_SCREEN["generate_dynamic_etfs.py<br>Dynamic Top 10 Funnel"]:::pipeline
            ETF_PYMC["export_etf_scorecard.py<br>Rust SV PyMC Engine"]:::model
            ETF_BROKER["etf_virtual_broker.py<br>VIX-Aware Broker"]:::broker
            ETF_SCORE["All_ETFs_Scorecard.xlsx"]:::output
        end

        %% UI & Backend
        BACKEND["FastAPI<br>Uvicorn Server"]:::pipeline
        WEB_UI["Premium 3D<br>Web UI"]:::ui
        GIT_VAULT["Git Vault<br>Auto-Backup"]:::ui
        EXEC_BRIEF["executive_brief.py<br>Executive Assistant"]:::pipeline

        %% Routing
        YF --> FAILOVER
        FAILOVER --> STOCK_SCREEN
        FAILOVER --> ETF_SCREEN
        FAILOVER --> FUNDAMENTALS
        FRED --> FUNDAMENTALS
        
        ENGINE_CONFIG --> MASTER
        MASTER --> STOCK_SCREEN
        MASTER --> ETF_SCREEN
        MASTER --> FUNDAMENTALS
        MASTER --> GIT_VAULT
        MASTER --> EXEC_BRIEF

        STOCK_SCREEN --> DATA_LOADER
        DATA_LOADER --> STOCK_PYMC
        YIELD_CURVE --> STOCK_PYMC
        STOCK_PYMC --> QA_MODELS
        QA_MODELS --> STOCK_SCORE
        SECTOR_GRAVITY --> STOCK_BROKER
        STOCK_SCORE --> STOCK_BROKER
        VIX --> STOCK_BROKER
        STOCK_BROKER --> SSOT_DB
        SSOT_DB -.-> INTRADAY_SNIPER
        VIX --> INTRADAY_SNIPER
        INTRADAY_SNIPER --> IDEMPOTENT_OVERRIDE
        IDEMPOTENT_OVERRIDE --> SSOT_DB
        SSOT_DB -.-> QA_BLACKLIST

        FUNDAMENTALS --> STOCK_DB
        STOCK_DB -.-> ETF_PYMC

        SUNDAY_SCREENER --> MASTER_ETF_JSON
        MASTER_ETF_JSON --> ETF_SCREEN
        ETF_SCREEN --> ETF_PYMC
        ETF_PYMC --> ETF_SCORE
        ETF_SCORE --> ETF_BROKER
        VIX --> ETF_BROKER

        SSOT_DB --> BACKEND
        STOCK_SCORE --> BACKEND
        ETF_SCORE --> BACKEND
        QA_BLACKLIST --> BACKEND
        BACKEND -.-> WEB_UI
        QA_UI_AGENT["qa_api_health.py<br>UI Health Poller"]:::script
        BACKEND -.-> QA_UI_AGENT

        SSOT_DB --> EXEC_BRIEF
        ETF_SCORE --> EXEC_BRIEF
"""

new_text = re.sub(r'<div class="mermaid">.*?</div>', '<div class="mermaid">\n' + mermaid_graph + '\n    </div>', text, flags=re.DOTALL)

with open('frontend/Architecture_Map.html', 'w', encoding='utf-8') as f:
    f.write(new_text)

print("Done")
