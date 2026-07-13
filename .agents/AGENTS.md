# QA Pipeline Rules

All agents working on the AntiGravity pipeline MUST run `qa_data_continuity_per_ticker.py` as part of the standard QA routine. This ensures that no individual stock is silently orphaned due to global max date checks or SQLite grandfathering failures.

## Pre-Market Health Check
Always ensure that master_watchdog.py is running before the market opens. If it is not running, forcefully resurrect it using PowerShell. A background cron schedule is set to wake the agent at 14:00 local time (GMT+3) daily to perform this check automatically.

## Zero-Hallucination Policy
NEVER answer questions about the system architecture, configuration, pipelines, or logic based on memory or assumptions. YOU MUST ALWAYS use `grep_search` and `view_file` to physically verify the exact code in the current codebase BEFORE answering. If you assume or guess, you are failing the user.
਍‭⨪䅑愠摮䰠杯捩污嘠牥晩捩瑡潩⩮㨪圠敨⁮潣普物業杮愠戠杵椠⁳楦數Ɽ䴠单⁔潬楧慣汬⁹敶楲祦琠敨漠瑵異⁴慤慴愠慧湩瑳戠獵湩獥⁳潣獮牴楡瑮⁳攨朮‮慭⁸潰楳楴湯猠穩湩⁧楬業獴⸩䤠⁦桴⁥畯灴瑵渠浵敢獲氠潯⁫慭桴浥瑡捩污祬椠灭獯楳汢⁥慢敳⁤湯琠敨猠獹整⁭畲敬ⱳ椠癮獥楴慧整琠敨搠瑡⁡潳牵散戠晥牯⁥敤汣牡湩⁧桴⁥獩畳⁥敲潳癬摥മ
## MIGRATION BACKUP FOLDER
Whenever generating a migration backup, it MUST be saved directly to **C:\Users\AviShemla\AG_BCK** so that Google Drive can sync it. DO NOT say it is on the Desktop or anywhere else.


## Scorecard Reading Protocol
When analyzing Top5_Bayesian_Scorecard_Formatted.xlsx or any ETF scorecard, ALWAYS use pd.read_excel(..., sheet_name=None) to dynamically parse sheets, as headers and ticker sheet orders change daily.

## QA Grandfathering Logic
The qa_data_continuity_per_ticker.py script must always cross-reference VIP_Tickers.json to correctly grandfather legacy stock holdings. Do not alter this logic to flag them as orphaned.

## Watchdog Survival Policy
NEVER kill the `master_watchdog.py` process during background housekeeping or when purging ghost tasks via `manage_task`. You MUST explicitly skip any task or process running the master watchdog. The master watchdog is the core OS-level supervisor of the dashboard and must never be terminated by an AI agent under any circumstances.
## Reporting Timestamp Rule
Whenever you generate a status report or system response for the user, you MUST include the current real-world timestamp so the user knows exactly when the report was generated.

## Systemic Persona Integrity Check
Any time you modify a Virtual Broker script or the Master Pipeline, you MUST verify that ALL 8 personas (Single Stocks and ETFs) generate valid pending orders or active HOLD states in the database. Silent skips via hardcoded continue statements are strictly forbidden. The qa_task_auditor.py must run after every nightly process to mathematically prove 100% persona participation.
