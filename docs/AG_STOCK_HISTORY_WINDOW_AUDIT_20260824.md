# AG stock history-window reconstruction — 2026-08-24

Mode: research/paper migration. This record performs no model fit, screening
write, recommendation, order, ledger update, or service activation.

## Source-code evidence: what AG actually did

The evidenced legacy stock path is
`export_bayesian_scorecard_TNX.py` -> `data_loader.extract_train_test_split`.

- `export_bayesian_scorecard_TNX.py` hard-codes
  `start_date = 2025-05-01`.
- `extract_train_test_split` sets
  `split_idx = len(historical_data) - 30`.
- Rows before that split are training data.
- The final 30 completed sessions are test/display data.
- The next business day is appended as the pending prediction row when needed.

Therefore AG did **not** fit the stock model using only 30 sessions. It trained
on all available observations from 2025-05-01 before the final 30-session
holdout. The user's recollection that the best predictions were associated
with “30 days” is consistent with AG's 30-session evaluation/output window,
not a 30-session fit window.

Legacy limitations remain material: this path reads CSV/Excel, uses a
hard-coded date, selects features on the full pre-split range in places, and
does not provide nested walk-forward promotion evidence. It is historical
behavior, not an approved production implementation.

## Direct Turso evidence for the validated Friday snapshot

Snapshot:
`market_features_2026-08-21_eee28adc62cbed61`.

- Live status: `VALIDATED`.
- Full history: 1,244 distinct sessions from 2021-09-08 through 2026-08-21.
- AG-compatible date range: 329 distinct sessions from 2025-05-01 through
  2026-08-21.
- AG-compatible training count before a final 30-session holdout: 299 sessions.
- 470 tickers contain all 329 sessions.
- FISV contains 328 sessions over the same date bounds.
- Expected universe: 471 tickers.

This direct readback resolves a stale document statement that called the
snapshot `STAGING`; the authoritative live record is `VALIDATED`.

## Proposed balanced screening preregistration

This is a proposal for owner review, not an executed configuration.

- Model family: selected predictive lead/lag chain.
- Chain depth: independently selected depth 1 through 5.
- Initial target-relative lag horizon: 1 through 7 trading sessions.
  Seven is the current operational search cap, not a theoretical maximum.
- Each run preregisters a finite candidate lag set within that horizon. Each
  selected edge records its own ticker and lag; no consecutive-lag or
  5->4->3 pattern is required.
- Purge/embargo: at least the maximum preregistered lag (7 sessions when the
  full initial horizon is searched).
- Never expand or change the lag horizon during an evidence or production run.
- Reassess the horizon in a separate research lane after every 63 newly
  completed trading sessions measured from the last accepted horizon review.
  Use only training data, multiplicity control, untouched walk-forward
  evaluation, and direct comparison with the incumbent horizon. Shorter or
  longer maxima may be proposed, but promotion requires explicit owner
  approval.
- Rolling training window: 252 sessions.
- Outer evaluation: two sequential 30-session test folds.
- Minimum OOS evidence: 60 sessions.
- Minimum fit observations: 126.
- Complete 471-symbol hypothesis family remains in the multiplicity
  denominator.
- Raw model outputs remain reportable even when promotion eligibility is zero.

For 329 aligned sessions this requires
`252 + 7 + (30 * 2) = 319` sessions and is therefore feasible while retaining
10 sessions of margin for feature alignment. It is materially closer to AG's
299-session fit history and 30-session evaluation horizon than the rejected
504-training-session configuration.

## Required comparison

A future evidence run should compare, without creating orders:

1. AG reconstruction: expanding history from 2025-05-01 with the final 30
   sessions as the observed holdout.
2. Balanced Codex candidate above: 252-session rolling training and two
   30-session purged outer folds.
3. A longer-history sensitivity lane using the same features and lags, so
   regime-window sensitivity is measured rather than assumed.

No lane may hide a Bayesian prediction. Promotion eligibility, persona policy,
sizing, VIX adjustment, and execution authorization remain separate.
