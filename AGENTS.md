# AntiGravity — Canonical Codex Context

This is the single entrypoint for Codex work on AntiGravity. It consolidates
the verified architecture and migration constraints from the imported snapshot.
It does not replace production evidence: when a question concerns live status,
holdings, recommendations, or an active service, verify the relevant live
system only after the user authorizes access.

## Scope and safety

- This workspace is an imported migration snapshot. Do not run pipelines,
  backtests, deployment scripts, email senders, or infrastructure commands
  unless the user explicitly requests that operation.
- Treat the system as paper/virtual trading in this snapshot. No brokerage API
  client was found in the inspected code; the sniper writes a virtual ledger.
- Never expose, reuse, or commit credentials. Secrets must come from an
  environment/secret manager, never source files, settings, logs, or reports.
- Preserve historical datasets and legacy artifacts until a reviewed cleanup
  plan identifies what can safely be archived or removed.

## Operating authority and non-negotiables

This file is the live operational authority for work in this repository. If it
   conflicts with `.agents/skills/anti-gravity-prime-directives/SKILL.md`,
`AntiGravity_Master_Blueprint.md`, `SYSTEM_STATE.md`, a historical note, or a
legacy script, this file takes precedence unless the user explicitly approves
an updated rule here.

1. **Zero hallucination; zero trust.** Do not state an architectural fact,
   production state, trade recommendation, service condition, or data result
   as true without evidence. Label statements as one of: source-code evidence,
   direct database evidence, live-service evidence, visual confirmation, or
   user-stated intent. When evidence is missing or conflicts, say so plainly.
2. **QA before reporting.** For each material change or conclusion, run the
   smallest safe verification that proves it: a read-only Turso query for
   database claims, a health/status check for service claims, source inspection
   for code claims, or visual confirmation for dashboard claims. Report the
   result, the evidence type, and any remaining uncertainty to the user.
3. **No autonomous production actions.** Legacy directives that require daily
   pipelines, sniper execution, emails, database writes, screenshots, or
   multi-agent audits do not authorize those actions. They run only after a
   specific user request and the safeguards in this file are satisfied.
4. **Turso is the production SSOT.** Production recommendations, holdings,
   orders, capital ledgers, scorecards, and reporting must use Turso-backed
   data. CSV and Excel files are not permitted as production data sources,
   caches, write targets, or fallbacks. A read-only legacy import/recovery
   exception requires explicit user approval and must be documented.
5. **No SQLite.** Do not create, query, update, or introduce SQLite databases
   or SQLite fallbacks for application behavior, tests representing production,
   or reporting. Existing SQLite artifacts are historical only and must not be
   treated as current truth.
6. **No Streamlit.** Do not run, restore, patch, add, or depend on Streamlit.
   The supported dashboard stack is FastAPI plus `frontend/`. Remove legacy
   Streamlit files and dependencies only through a reviewed cleanup change.

### Operating mode and automation authority

- The current mode is **FROZEN/RESEARCH**. The sniper, nightly pipeline,
  watchdog, email dispatcher, model promotion, order staging, and any other
  automatic action remain inactive unless the user explicitly authorizes a
  mode change or a specific run.
- Preserve those capabilities in source and configuration; freezing authority
  is not permission to delete them. Activation progresses only through
  **FROZEN/RESEARCH -> PAPER-MANUAL -> PAPER-AUTOMATED -> LIVE**.
- A mode transition requires recorded scope, prerequisites, risk controls,
  rollback/kill-switch procedure, verification evidence, and explicit user
  approval. Approval for one run or one component does not activate another.
- Legacy instructions that say an agent "must" run the sniper, nightly jobs,
  email, Prefect recovery, screenshots, or healing are capability descriptions,
  not current authority. The safer rule in this file controls.

## Capital Safety Charter

Protecting capital and preserving an accurate record of every decision are
more important than availability, automation speed, or model output. This
project is currently a virtual/paper-trading system. No real broker API client
has been verified in the source snapshot. Treat that boundary as absolute.

### Execution authority

- The permitted progression is **research -> backtest -> paper/shadow -> live**.
  A strategy may advance only with documented evidence from the preceding mode.
- No external live order, brokerage-account connection, funding action, or
  production execution integration is permitted without the user's explicit
  written approval of the broker, account scope, strategy, and go-live plan.
- Any live phase must use a dedicated, least-privilege broker credential and
  account; never use personal credentials in source, logs, chat, or reports.
- A globally effective kill switch must block new order submission immediately
  while retaining read-only monitoring, reconciliation, and evidence capture.

### Hard risk controls

- Enforce configurable, tested limits before an order can leave the system:
  maximum order and position size, gross/net exposure, sector and correlated
  exposure, leverage, turnover, daily loss, rolling drawdown, and order rate.
- A missing, stale, conflicting, non-finite, or implausible input is a
  **no-trade** condition. The system must fail closed, not guess or substitute.
- Enforce market-calendar/session validation, trading-halting/circuit-breaker
  awareness, price/volume sanity bounds, and corporate-action handling before
  creating an executable order.
- Risk limits, kill-switch state, and any manual override must be checked at
  recommendation time and again immediately before order submission.

### Model and data governance

- Promotion requires reproducible out-of-sample and walk-forward results,
  calibration checks, transaction-cost/slippage assumptions, and documented
  comparison against an appropriate baseline.
- Monitor data freshness, completeness, schema changes, distribution drift,
  model drift, and feature validity. Any failed control blocks promotion and
  execution until investigated.
- Never infer causal, predictive, or profitability claims from in-sample
  results alone. Report uncertainty and adverse scenarios alongside returns.
- Version source data, model code, configuration, dependencies, and generated
  recommendations so any decision can be reproduced exactly.

### Order integrity and reconciliation

- Every recommendation, approval, order, broker acknowledgement, fill,
  cancellation, rejection, position update, and ledger entry must carry stable
  identifiers and timestamps.
- Submission must be idempotent. A retry must not create an additional order
  or duplicate capital-ledger entry.
- Reconcile intended orders, broker responses, fills, cash, positions, and
  realized/unrealized P&L against the Turso ledger before declaring success.
- A reconciliation mismatch is a blocking incident: halt new execution,
  preserve evidence, report it to the user, and resolve it before resuming.

### Nightly-to-open execution contract

- The nightly process may create only a **dated proposed plan** from the last
  fully completed NYSE session. It must record the source-session date, data
  snapshot/version, model/configuration version, persona, recommendation, and
  intended units in Turso.
- The intraday sniper is an execution consumer, not a second model authority:
  it may consume only one matching, approved, unexpired plan and must not
  silently infer or substitute BUY/SELL/HOLD decisions or quantities.
- Market scheduling must be derived from the NYSE calendar and the
  `America/New_York` timezone, never a hard-coded Israel clock. NYSE regular
  opening is 09:30 New York time; in the August 2026 Israel/New York offset it
  corresponds to 16:30 Israel time, while DST-transition weeks require the
  timezone conversion rather than an assumption.
- Immediately before execution, validate: matching plan/session dates; market
  state; data freshness; model and risk-control status; kill-switch state;
  plan uniqueness/idempotency; and prior-ledger reconciliation. Any failure is
  a no-trade condition that preserves the plan and records the reason.
- After each action, record the outcome and reconcile it to cash, positions,
  and the Turso ledger before permitting the next action.

### Operational controls and reporting

- Require a written change plan, focused test evidence, rollback path, and user
  approval before changing any execution, risk, model, schema, deployment, or
  broker-integration behavior.
- Separate read-only monitoring credentials from write/execution credentials;
  rotate secrets, minimize privileges, and audit all credential access.
- Maintain append-only decision and incident records in the authoritative
  database. Do not overwrite historical outcomes to make results look better.
- Every material report must state: mode (research/paper/live), evidence source,
  checked controls, outstanding failures or uncertainty, and whether capital was
  at risk. Never call a run green while a critical check is unresolved.
- Before any live deployment, obtain any applicable legal, regulatory,
  brokerage, and security review for the jurisdiction and account structure.

## Intended production architecture

```text
Yahoo Finance + FRED + VIX
  -> downloader/failover (Tiingo fallback)
  -> stock and ETF screening
  -> lagged Bayesian/PyMC scorecards + shadow deep-learning scorecards
  -> model QA and risk filters
  -> virtual stock/ETF brokers (persona + Kelly sizing)
  -> Turso pending_orders
  -> intraday sniper (market-hours VWAP/VIX/momentum controls)
  -> Turso capital ledgers and trade records
  -> FastAPI -> Oracle dashboard and executive reporting
```

The documented target deployment is Vultr-hosted orchestration/services with
Turso as the cloud single source of truth. The documented services include the
API/dashboard, intraday sniper, and VIX monitor. The dashboard has portfolio,
ETF, model-arena, trade-autopsy, and architecture views.

## Core components

- `master_pipeline.py`: orchestrates nightly work and QA stages.
- `data_loader.py`: builds predictor matrices from historical market data.
- `export_bayesian_scorecard_TNX.py`: stock Bayesian scorecards.
- `export_etf_scorecard.py`: ETF Bayesian/stochastic-volatility scorecards.
- `daily_dl_inference.py` and `weekend_dl_trainer.py`: shadow ML workflow.
- `virtual_broker.py` and `etf_virtual_broker.py`: portfolio staging.
- `intraday_tracker.py`: reads pending state, applies intraday controls, and
  commits the final virtual ledger state.
- `database_manager.py`: Turso tables and read/write helpers.
- `server.py` and `frontend/`: FastAPI API plus the Oracle web dashboard.
- `dashboard.py` and `dashboard_v1.py`: retired Streamlit dashboards retained
  only as historical artifacts in this imported snapshot. GitHub `master` had
  no Streamlit code-search matches on 2026-08-21; do not restore, run, or patch
  these scripts. Preserve them until a reviewed archival/removal plan is
  approved.

## Operational invariants to preserve

- Production state is intended to be Turso-backed; `pending_orders`, capital
  ledgers, scorecards, and model-comparison data must remain traceable.
- Nightly recommendation generation and market-hours execution are separate
  stages connected through pending orders.
- The execution layer must be idempotent: re-runs cannot duplicate ledger
  entries or orders.
- Risk personas, allocation caps, VIX-aware controls, and execution guards are
  domain behavior. Do not change them without a specific, reviewed request.
- UI data contracts must be updated with backend schema, model-name, or persona
  changes.

## Snapshot conflicts to resolve before relying on production behavior

The imported archive contains both legacy and newer implementation paths. Do
not silently choose between them:

1. Documentation says Turso/cloud-only, while parts of the source still refer
   to local SQLite, CSV/Excel fallbacks, and Windows-local paths.
2. The latest Blueprint describes Vultr cron/systemd services, while source and
   `prefect.yaml` retain Windows/Python scheduler assumptions.
3. The operating rulebook requires Gmail SMTP only, but compatibility code
   retains Outlook-style abstractions.
4. The project documents PyTensor NUTS as the active sampler; some historical
   model files still reference `nutpie`.
5. The archive contains hard-coded credential material. It must be rotated and
   removed from source before any repository or deployment work.

Until these are reconciled against authorized production evidence, label the
snapshot behavior as **unverified** rather than current.

## Model dependency contract — user-stated intent, pending implementation proof

- The stock layer is intended to be a causal Bayesian/PyMC network whose edges
  may use independently selected lags. **Chain length and per-edge lag are
  separate parameters.** A chain need not have five edges, and its lag tuple
  need not be consecutive, monotonic, or capped at five; for example, a
  candidate may use lags 7, 5, and 2. The lag search domain, maximum chain
  length, edge direction, and whether lags are target-relative or
  edge-relative must be preregistered before a run. Lag selection must use
  training information only, control multiple-testing/overfitting risk, and
  pass untouched outer walk-forward validation. Its
  dated, statistically defensible outputs are intended to inform ETF-model
  priors and/or ETF feature inputs, not merely a dashboard display.
- Before any model run, a **spec-equivalence gate** must compare the executable
  configuration with the approved model contract. A mismatch blocks the run.
  If discovered after launch, stop safely, mark the run `FAILED` with the exact
  rejected assumption, retain evidence, and prohibit every partial output from
  promotion, order staging, or sniper consumption.
- Preserve the raw Bayesian posterior output separately from decision policy.
  For every prediction, report the historical AntiGravity eligibility result,
  the stricter Codex research result, and a proposed balanced result with each
  individual gate and reason visible. Never silently turn a probabilistic model
  into a deterministic claim, and never hide all research output merely because
  a production gate blocks trading.
- Every run must bind to an immutable input snapshot and record data provider,
  symbol universe, available-at cutoff, feature/lag specification, code commit,
  configuration hash, sampler, seed policy, and output lineage. A fallback
  provider cannot silently change the snapshot.
- Historical stock/ETF quarantine membership and automatic release rules are
  evidence only. Start the repaired system with a fresh, empty quarantine;
  future entries and releases require recorded reason codes, dates, evidence,
  and the approved policy version.
- The ETF layer is separately Bayesian/PyMC. It must use the relevant
  stock-derived evidence and its identified constituent "whales" to weight and
  re-evaluate the ETF. The dynamic universe may replace an ETF when the
  re-evaluation does not support retaining it.
- Each ETF input or prior must record its contributing stock scorecard
  identifiers, constituent weights, source date, available-at timestamp,
  transformation, feature/prior role, and model version. It may use only
  information available before the ETF prediction cutoff; otherwise it is
  rejected as potential look-ahead bias.
- Existing source code has not yet been shown to meet this contract. Its
  current whale-prior path reads a legacy fundamentals CSV; do not claim the
  intended stock-PyMC-to-ETF integration or dynamic replacement behavior until
  the Turso-backed implementation and tests are verified.

## Working method

1. Read this file first, then the relevant source files.
2. Use `AntiGravity_Master_Blueprint.md` and `Architecture_Map.html` for the
   intended design; use code and authorized runtime evidence for actual state.
3. For a requested change, map its effects across data ingestion, model output,
   broker staging, intraday settlement, database schema, backend API, and UI.
4. Run the smallest relevant local verification; do not contact production by
   default.
5. Record any new architectural decision here and retire superseded notes only
   after confirmation.

## Supporting references

- `.agents/skills/anti-gravity-prime-directives/SKILL.md`: production QA and
  operating directives.
- `AntiGravity_Master_Blueprint.md`: architecture history and recovery notes.
- `Architecture_Map.html`: visual component/data-flow map.
- `SYSTEM_STATE.md`, `roadmap.md`, and `Context_Summary.md`: historical state
  and pending work; these may contain stale material.

## Codex migration handoff — 2026-08-21

### Access status

- **Google Drive:** connected and read-only profile access verified. No Drive
  files were changed.
- **GitHub:** remote read access to `AviShemla/AntiGravity` verified through
  the GitHub connection. Remote write/push access remains untested.
- **Gmail:** connected; a read-only profile check succeeded. No messages were
  read, sent, or changed.
- **Turso:** the user can access the `theoracle` cloud database dashboard.
  Existing database tokens were invalidated during credential rotation. A
  replacement token is stored only in the ignored local `.env` and the
  root-owned VPS `.env`; read-only Turso health checks from both environments
  returned HTTP 200 on 2026-08-21. Do not request, paste, display, or
  screenshot a token.
- **Vultr:** user-controlled SSH access to `AntiGravity-Node` was verified.
  A non-root `codexops` account was created, granted sudo, and its sudo access
  was tested. The exposed root password was rotated. Independent key-based
  Codex SSH login as `codexops` was verified on 2026-08-21 using the dedicated
  operations key. The user explicitly approved a passwordless sudo policy for
  this dedicated operations account; independent `sudo` elevation was verified
  with a read-only effective-user-ID check. Use this authority only for an
  explicit task and preserve the service and production safeguards below.

### Authorized production observations (read-only unless stated above)

- Do not reboot or apply OS updates yet; the host reports pending updates and a
  reboot requirement, but neither was authorized.
- `ag-vix.service` is enabled and active, producing VIX updates.
- `ag-sniper.service` is disabled and inactive; do not start it without an
  explicit request and a Turso/configuration review.
- On 2026-08-21, the user authorized a brief dashboard handover. The manual
  port-80 Uvicorn process was stopped and `ag-uvicorn.service` was started.
  It is now active, owns port 80, and the local dashboard HTTP check returned
  200. Its database-backed `/api/holdings` endpoint was also verified after
  handover (HTTP 200, required response fields present, 40-point equity curve).
  This service is now the intended dashboard owner; do not create a second
  manual Uvicorn process.
- Vultr displayed a CPU-rate-limit notice. This has not been investigated.
- The live server's `/opt/antigravity/.env` was previously world-readable and
  world-writable. On 2026-08-21, its Turso credential was replaced with the
  current rotated credential and the file was secured as `root:root` mode
  `600`. Do not expose its contents.

### Resume order

1. Verify the dashboard's database-backed routes after the controlled service
   handover, without creating or changing production records.
2. Produce a deployment cleanup plan for the now-managed dashboard service,
   disabled sniper, and VIX service before making further service changes.
3. Compare any newer authorized Git source with this imported snapshot before
   adopting or overwriting files.

### User-stated intended production authority

The user has stated that the intended operating role is:

- **Turso `theoracle-avishe`:** full read/write administrative pipeline access,
  including data and schema operations through its HTTPS bearer-token pipeline.
- **Vultr production VPS:** root-level administration for files, services,
  scheduling, processes, ports, and firewall configuration.

This describes the requested authority level, not verified live connectivity.
Use it only for an explicit task. Always verify the exact target and preserve
the operational safeguards above before destructive database, service,
process, firewall, or filesystem operations.
