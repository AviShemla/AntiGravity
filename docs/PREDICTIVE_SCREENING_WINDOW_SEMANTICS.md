# Predictive screening window semantics

Contract: `screening-window-separation-v1-20260825`.

This contract separates two statistically different quantities. They must not
be substituted for one another or compared under an ambiguous "lookback"
label.

## Fitted-training evidence

`training_window_sessions` is the governed history used to fit every inner
and outer classifier and its own-lag baseline. It remains subject to the
existing minimum of 126 completed observations after feature lags. Under the
current nested contract, preflight requires:

```text
inner_test = min(test_sessions, max(20, floor(training_window_sessions / 5)))
inner_fit = training_window_sessions - inner_test - purge_sessions
inner_fit >= min_fit_observations + max_depth
```

For `test=30`, `purge=7`, `min_fit=126`, and `max_depth=5`, the smallest
feasible fitted-training window is 168 sessions.

## Signal discovery recency

`signal_lookback_sessions` has the governed comparison domain `30`, `60`,
`126`, or `252`. It selects the exact trailing slice used only to rank lag
edges and technical signals inside each training boundary. It never shortens
the rows used to fit or score a classifier.

Current governed status:

| Signal window | Status |
| --- | --- |
| 30 | `BLOCKED_MIN_50_COMPLETE_PAIRS` |
| 60 | `ENABLED` |
| 126 | `ENABLED` |
| 252 | `ENABLED` |

Keeping 30 in the domain records the requested research arm; `BLOCKED` means
the current method cannot execute it, not that it was silently removed.

The requested signal window must fit wholly inside the inner training
evidence. Preflight rejects a configuration instead of silently truncating the
signal window. Under the current `test=30` and `purge=7` contract, the 30,
60, and 126 signal arms fit at the 168-session fitted-training boundary; the
252-session arm requires at least 289 fitted-training sessions
(`289 - 30 - 7 = 252`).

The existing candidate-significance rule also remains unchanged: fewer than
50 complete paired observations cannot establish an admissible discovery
feature. For a signal window `S` and the smallest candidate lag `L`, the
best-case pair capacity is `S - L`. With the approved lag-1 candidate, a
30-session window can produce at most 29 pairs, so it is guaranteed to fail.
Preflight therefore blocks it before credentials, Turso access, or run
creation. The exact mathematical boundary is 49 pairs rejected and 50 pairs
accepted for significance evaluation; the gate itself is not weakened.

## Leakage boundary

For each outer fold:

1. Signal ranking sees only the trailing configured signal slice inside the
   outer training boundary.
2. Depth selection repeats signal ranking inside the purged inner-training
   boundary.
3. Model fitting uses the complete governed inner or outer fitted-training
   positions, never only the signal slice.
4. Neither feature discovery nor fitting sees the corresponding test rows.

The CLI requires `--signal-lookback-sessions` for every new evidence run.
The contract identifier, both window values, and the governed signal-window
status are persisted in `config_json`.
Legacy results without these fields retain their historical meaning and fail
the new contract audit rather than being silently reinterpreted.
