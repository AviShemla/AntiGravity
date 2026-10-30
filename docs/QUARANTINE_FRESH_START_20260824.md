# Quarantine fresh-start design — 2026-08-24

Status: **applied and read back successfully** on 2026-08-24. GitHub
implementation commit: `5147d922ae45d57e067d11b86ee04921a802df88`.

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

## Applied Turso evidence

- Evidence SHA-256:
  `6082de5547fc380e0cb27a11ce80f7646c47e4556e4dd4d50764200943f2c467`.
- Prior registry `etf_registry_20260822_v1`: `SUPERSEDED` and retained.
- Successor registry `etf_registry_20260824_fresh_v2`: `APPROVED`.
- Successor usage counts: 11 `MODEL_CANDIDATE`, 14 `VALUATION_ONLY`, one
  `BENCHMARK`, and zero `QUARANTINED`.
- Reset events: STOCK and ETF `LEGACY_STRIKE_BLACKLIST`, both effective
  2026-08-21 and approved by AviShemla.
- Historical SPY quarantined scorecard rows retained: 20.
- Protected counts after the write: four `pending_orders`, 299
  `capital_ledgers`, zero `model_runs`, and zero `model_scorecards`.
- `ag-sniper`, nightly, and QA services remained inactive/failed-off. The
  read-only dashboard continued to return HTTP 200.

## Remaining production gate

The reset does not authorize a model recommendation or execution. Stock-first
model input, per-prediction eligibility comparison, lineage, and no-trade
preflight must still pass before a future model run or pending-order write.
