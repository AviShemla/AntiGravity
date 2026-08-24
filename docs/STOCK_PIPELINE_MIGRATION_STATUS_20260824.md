# Stock Pipeline Migration Status — 2026-08-24

Mode: research/paper migration. No model was fitted, no recommendation or
order was created, and no trading service was activated during this work.

## Friday market snapshot candidate

Candidate snapshot:
`market_features_2026-08-21_eee28adc62cbed61`.

Direct Turso evidence:

- Status remains `STAGING`.
- Source session: `2026-08-21`.
- Provider declaration: `TIINGO_EOD+YAHOO_FINANCE`.
- Stored content checksum:
  `eee28adc62cbed619bd66047925a0227e18a8f8057421a4282336bb7803ab4c2`.
- Exact stored counts: 582,798 rows and 471 distinct tickers.
- Latest-session counts: 471 rows and 471 distinct tickers.
- Structural QA: zero missing core fields, non-positive OHLC values, OHLC
  bound violations, negative volumes, invalid RSI/ADX values, future rows, or
  latest-session model-field gaps.
- Coverage QA: all 471 tickers contain all 130 most recent sessions with zero
  missing return, VIX, or TNX fields.
- Macro lineage: `^VIX` and `^TNX` both have Yahoo provider evidence through
  the exact source session, with stable 64-character SHA-256 checksums.
- Independent Tiingo delta:
  `tiingo-delta-2026-08-21-9ee0e6bd3dd3-d6741d159206` is `COMPLETE` with
  exactly 471 ticker rows for 2026-08-21.
- Friday OHLC comparison against that Tiingo delta covered all 471 tickers.
  Provider values differ at sub-cent precision for most symbols; maximum
  absolute differences were approximately 0.00503 or less for each OHLC
  field. No tolerance or rounding rule has been used to promote the snapshot.

Promotion remains a separate owner-approved database action. The snapshot has
not been promoted by this checkpoint.

## Recovered stock migration modules

The recovered DB-first path contains:

- immutable Turso input selection and count verification;
- bounded feature freshness and complete stock screening matrices;
- nested, purged walk-forward causal-chain screening;
- append-only screening evidence;
- an approved-universe/readiness preflight;
- leakage-safe 30-session stock model matrices;
- a PyMC direction and robust Student-t return engine;
- sampler QA for divergences, R-hat, ESS, chains, and E-BFMI;
- a pure three-lane eligibility comparison for every posterior prediction.

The three eligibility lanes are intentionally separate:

1. Legacy AG behavior reproduces the scorecard and persona thresholds actually
   found in source, including legacy Kelly and flat-fallback behavior.
2. Strict Codex uses posterior interval exclusion of 50% plus positive/negative
   expected return after recorded costs.
3. Balanced paper candidate keeps the legacy persona mean-probability threshold
   but requires signed net expected return. Posterior uncertainty remains
   visible and is never discarded.

Raw Bayesian output is always reported. A failed safety or promotion gate can
produce `NO_TRADE`, but cannot hide or rewrite the model prediction.

## Verification

The isolated Vultr test environment passed 65 focused tests covering input
governance, feature freshness, screening, sampler QA, stock dataset creation,
stock preflight, posterior summary, and eligibility comparison.

## Remaining gates before a stock model run

1. Owner approval to promote the exact Friday market snapshot above.
2. A Friday predictive-screening run and explicit review of its complete
   results. This is append-only research evidence, not an order.
3. An approved Friday stock-universe snapshot derived from reviewed screening
   evidence. Zero eligible candidates must remain an explicit no-trade result.
4. A no-write stock preflight against the exact market and universe snapshots.
5. Separate owner approval before fitting PyMC or writing any model scorecard.

`ag-sniper.service`, `antigravity-nightly.timer`, and
`antigravity-qa-watchdog.timer` must remain inactive and disabled throughout
these gates.
