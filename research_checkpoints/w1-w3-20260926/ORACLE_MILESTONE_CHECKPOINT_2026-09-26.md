# Oracle research checkpoint: September 26, 2026

## Agreed workstream status

| Workstream | Status | Scope and evidence |
| --- | --- | --- |
| W1 | DONE | User-approved population of 474 instruments: 457 stocks and 17 ETFs; membership saved in ORACLE_W1_GOVERNED_UNIVERSE_2026-09-25.json. This does not establish the original top-50-per-sector ranking. |
| W2 | DONE | Frozen, reconstructible input version oracle-w2-20260925-delta-v1. All 597139 rows, 474 instruments and 34 model columns passed reconstruction comparison; local selector bound. |
| W3 | DONE: agreed baseline computation | Corrected daily-lag forecasts executed against frozen W2. 473 instruments evaluated, 56760 dated predictions retained. SNDK explicitly excluded: 380 observations versus 416 required. |
| W4 | IN PROGRESS | Frozen-input adapter passed the actual dataset-builder fixture. No Bayesian fit or deployed model runner. Latest saved screening runs have zero eligible instruments. |
| W5-W8 | PENDING | Not completed by this checkpoint. |

These are the agreed preparation/baseline statuses, not automatic promotion of
the broader migration registry, model acceptance, causal identification, or
trading readiness. This status addendum takes precedence over earlier W2/W3
progress statements for this specific scope; earlier records remain historical.

## W2 result

- Reuses retained August base market_features_2026-08-25_5b1044ee45605a3d.
- Preserves 10429 additions and 1458657 changed cells; zero deleted keys.
- Compressed delta payload: 17573660 bytes. This is not a billed-storage measurement.
- Version manifest SHA-256: fbfc4cbf4426b7b27cf312fd4fc57eea505cae1366262a6ff952f56250882be1.
- Operational created_at_utc is excluded from the 34 model columns.
- Historical point-in-time availability is NOT established merely by freezing currently observed values.

## Corrected W3 results

| Baseline | Brier score; lower is better |
| --- | --- |
| Majority direction | 0.5022727272727273 |
| Constant training rate | 0.2510391281709043 |
| Corrected lag-one logistic | 0.25149098132782993 |
| Constant 0.5 probability reference | 0.25 |

The corrected run supersedes the earlier provisional W3 scores. None of these
three baseline scores beats the constant-0.5 reference on this sample. No
predictive or economic superiority is established.

The run uses four 30-observation test folds, 289 training observations, a
7-observation purge, and 200 logistic optimizer iterations. It uses the first
416 observations per eligible instrument, not aligned common-calendar folds.
Optimizer convergence, survivorship bias and historical point-in-time inputs
remain limitations, not silently resolved findings.

Full per-instrument dated predictions are retained on Vultr under
/var/lib/codex-oracle/research/w3-frozen-c6df1552eb5e6640. Their hashes are in
ORACLE_W3_CORRECTED_RESULTS_2026-09-26.json. This checkpoint stores that manifest,
not a second copy of market history.

## W4 resume point

- oracle_w4_frozen_input.py binds the existing builder to frozen W2, an explicit cutoff, and caller-supplied calendar sessions.
- The input-only AAPL/MSFT fixture passed with 30 x 8 training and 1 x 8 prediction inputs. It does not statistically approve that example chain.
- Installed calendar /etc/codex-oracle/nyse-calendar-2026.json matched SHA-256 ac02ecb58e488f1e671308548edd60768afd6676bd7156ba2ff762a8f6f1ee1d.
- Market snapshots are present. The empty stock-universe configuration is a model-selection issue, not missing extracted data.
- Saved screening contains 25 runs and 4334 results. Five older eligible rows belong to a different fixed-macro model: CRL, HRL, REGN, UPS and VICI. Do not substitute them for W4 variable lead-lag acceptance.
- Next: inspect the latest variable lead-lag rejection details before proposing a new screening run. Do not weaken eligibility or invent a chain.

## Preservation and boundaries

- No nightly runtime, schedule, watchdog, production data, broker or trading changes are included.
- Git checkpoint is prepared in a separate checkout. Existing market_data_provider.py changes and authorization-envelope deletion remain untouched.
- Only named source, manifest, result and report files are included. Credentials, caches, staging backups, raw logs and obsolete temporary runners are excluded.
- Git push and Drive upload receipts are recorded separately; this document alone does not assert successful synchronization.
- Lessons applied: ORA-INC-001, 004, 008, 012, 018, 022, 039, 045, 046.
