# Quarantine fresh-start design — 2026-08-24

Status: implementation prepared and unit-tested; Turso reset event and ETF
registry successor are not yet applied by this document.

## Reconstructed AntiGravity meanings

AntiGravity used “quarantine” for four different controls:

1. A run-local JSON map of symbols whose Yahoo/Tiingo fetch failed. It was
   cleared at the beginning of each run and forced a dummy HOLD scorecard.
2. A model-failure HOLD marker in legacy scorecards. Existing holdings were
   frozen rather than liquidated on missing evidence.
3. A persona-specific strike blacklist: three or more negative-PnL sessions in
   the latest 15 ledger sessions blocked new capital while retaining holdings.
4. A versioned ETF registry classification for historical experiments or
   instruments without sufficient approved model-use evidence.

These controls must not be merged. Historical model failures, losses, and
ledger anomalies remain evidence and must never be deleted.

## Live evidence before reset

- Vultr `financial_data/quarantined_tickers.json` is `{}`.
- Turso contains zero `model_runs` and zero pending rows with quarantine text.
- Legacy scorecards contain 20 SPY dummy-HOLD rows dated 2026-06-22 through
  2026-06-26. They remain historical evidence.
- Approved ETF registry `etf_registry_20260822_v1` contains 12 quarantined
  symbols: IGV, ITB, IYH, MRVU, MSTZ, MTUM, MULL, NBIL, RDVY, RGTZ, SMCX,
  and SRTY.
- The latest ledger session is 2026-08-20. Applying a strike reset effective
  2026-08-21 therefore starts every persona with zero post-reset strikes.

## Safe reset semantics

1. Insert an append-only `quarantine_reset_events` row effective 2026-08-21
   for the legacy strike mechanism. The broker/model may count only losses on
   or after that date. Old ledger rows remain unchanged.
2. Every immutable model run begins with no quarantined instruments. A symbol
   is quarantined only within that run when its required input or sampler gate
   fails. A later run retries it from fresh evidence.
3. Create a successor ETF registry version. Previously quarantined ETF names
   re-enter data collection as `VALUATION_ONLY`; this removes quarantine but
   does not authorize a BUY. Promotion to `MODEL_CANDIDATE` requires the same
   forward-only validation used for all ETFs.
4. Never clear historical SPY dummy rows or the 26 legacy ledger anomalies.

## Production gate

No reset event, registry successor, recommendation, pending order, or service
change occurs until the migration read-back, exact before/after counts, and
stock-first model preflight pass.
