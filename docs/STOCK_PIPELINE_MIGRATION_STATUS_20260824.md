# Stock Pipeline Migration Status — 2026-08-24

Mode: research/paper migration. No model was fitted, no recommendation or
order was created, and no trading service was activated during this work.

## Friday validated market snapshot

Validated snapshot:
`market_features_2026-08-21_eee28adc62cbed61`.

Direct Turso evidence:

- Status is `VALIDATED`.
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
  field.
- A direct Turso readback on 2026-08-24 confirmed the exact snapshot is
  `VALIDATED`, with 582,798 expected rows, 471 expected tickers, and
  `available_at_utc=2026-08-23T06:46:36.910435+00:00`.

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
- an append-only per-prediction audit contract that stores raw posterior
  evidence, every AG/Codex/balanced criterion result, explicit Dynamic base
  persona resolution, hard-gate failures, and both legacy and shadow sizing;
- deterministic canonical EOD revision selection and reconciliation;
- exact affected-window recomputation planning for recursive features; and
- an exact, checksummed replacement-patch contract that refuses missing,
  duplicate, extra, or non-canonical ticker/session keys.

Direct Turso schema readback confirmed that both
`predictive_screening_results` and `stock_universe_config` contain all five
independent `lag1_sessions` through `lag5_sessions` columns. The lag schema is
therefore no longer an open migration blocker.

Predictive-chain discovery now searches depth 1 through 5 by default. Each
selected edge carries its own preregistered positive session lag; chains do
not have to use consecutive lags or a descending 5→4→3 pattern. The executable
contract `stock-lag-horizon-v1-20260824` currently permits a finite
preregistered subset of lags 1 through 7 and requires a formal horizon review
after every 63 newly completed trading sessions. Seven is an operational cap,
not a theoretical maximum. The completion audit fails closed when the contract,
review interval, or maximum lag differs.

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

The isolated Vultr test environment passed the focused stock checks. Following
the executable lag-governance and explicit-preregistration changes, 258
non-credentialed tests passed and the two Turso ledger tests passed separately
under the protected root environment using SELECT-only code paths: 260 total,
zero assertion failures. `git diff --check` passed. The apparent secret-scan
matches were inspected without printing values and were two environment-variable
or placeholder references, not committed credentials. GitHub `origin/master`
matched the clean Vultr worktree before this documentation update.

## Read-only dashboard and legacy-runtime audit

A direct five-tab browser QA on 2026-08-24 verified:

- Stocks: one visible tab container, 11 portfolio rows, zero duplicate rows.
- ETFs: one visible tab container, 21 portfolio rows, zero duplicate rows.
- Arena: exactly eight model cards, 39 ledger rows, zero duplicate rows.
- Autopsy: four charts, two tables, 143 forensic rows, zero duplicate rows.
- Blueprint: exactly one each of sections 1 through 5.
- Browser console: zero warning or error entries during the tab traversal.

Full-page screenshots initially appeared to repeat content. DOM counts and
ordinary viewport screenshots proved that this was capture stitching, not a
duplicate dashboard render. No UI code was changed on that false signal.

The frozen `/opt/antigravity/virtual_broker.py` is the evidenced legacy
production-selection path: orchestration scripts invoke `virtual_broker.py`,
not `virtual_broker_v2.py`. Its persona thresholds are 0.65 Conservative,
0.60 Neutral, and 0.55 BallsForBrains, with 0.25/0.50/0.90 Kelly multipliers
and 10%/10%/15% caps. It still reads Excel scorecards and contains historical
CSV logic, so it violates the replacement architecture and must never be
reactivated as the governed broker. The DB-first comparison preserves these
values only as auditable legacy behavior; it does not call that broker.

## Remaining gates before a stock model run

1. Verify the explicitly approved one-time 2026-08-24 post-close ingestion by
   terminal service state, durable logs, and independent Turso readback.
2. The additive canonical market-lineage schema migration was applied and
   read back at exact SHA-256
   `db10c366a7ef6adfdf6dbe6f4c39fe1fe4b3a2e573f393ed099e3b3028df542a`.
   Integrating and executing the exact feature replacement writer remains
   pending; no replacement feature values have been promoted.
3. A complete Friday predictive-screening run using the corrected,
   preregistered variable-depth/independent-lag configuration, followed by
   explicit review. The latest Friday run is failed and partial: 15 stored
   result rows, zero evaluated rows, and zero eligible rows. It is not usable.
4. An approved Friday stock-universe snapshot derived from reviewed screening
   evidence. Zero eligible candidates must remain an explicit no-trade result.
5. A no-write stock preflight against the exact market and universe snapshots.
6. Separate owner approval before fitting PyMC or writing any model scorecard.
7. The additive prediction-audit migration was applied and read back at
   exact approved SHA-256
   `8ff5931429ceaba8713ec6d7f2efafa343292e0e4727b7835e782f31600d95c2`.
   Populating it remains gated on an approved, completed model run.

`ag-sniper.service`, `antigravity-nightly.timer`, and
`antigravity-qa-watchdog.timer` must remain inactive and disabled throughout
these gates.
