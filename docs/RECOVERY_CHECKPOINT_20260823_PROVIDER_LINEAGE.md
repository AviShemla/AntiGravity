# Recovery checkpoint — provider lineage and Friday staging — 2026-08-23

Mode: paper/virtual recovery. Trading, nightly, QA, model export, order
generation, and the intraday sniper remain frozen. No broker action was
attempted and no capital was at risk.

## Applied owner-approved provider-lineage schema

- Applied CREATE-only migration:
  `migrations/20260822_market_provider_lineage_additive.sql`.
- Reviewed migration SHA-256:
  `4698f46a6dd7ae96e63e55ea50c5bbd82b55bcf456576b5d30d77bf1a5d6ae78`.
- The migration created only:
  - table `market_data_provider_lineage`;
  - index `idx_market_provider_lineage_lookup`.
- Existing market, model, order, ledger, and scorecard rows were not updated or
  deleted.

## First Friday staging attempt — retained as rejected evidence

Snapshot `market_features_2026-08-21_e2f7b9073fedf04e` remains in `STAGING`
and must not be promoted.

- 582,797 feature rows across 471 controlled instruments.
- Structural checks passed.
- Exact recent-session audit found MNST missing NYSE session 2026-08-10.
- Direct provider comparison proved Yahoo omitted that session while Tiingo
  included it.

## Fail-closed provider repair

`scripts/rebuild_market_features_to_turso.py` now builds the exact recent NYSE
session calendar before staging. When the primary source has a required-session
gap, it replaces the entire ticker series with Tiingo. It never forward-fills a
missing trading session and never mixes one replacement row into an otherwise
primary-provider series. If the fallback is also incomplete, the rebuild fails
closed.

The focused rebuild suite contains 18 tests and passed in isolated VPS
execution.

## Corrected Friday staging evidence

Snapshot `market_features_2026-08-21_eee28adc62cbed61` remains in `STAGING`.

- Source session: 2026-08-21.
- 582,798 feature rows across 471 controlled instruments.
- Date range: 2021-09-08 through 2026-08-21.
- Staged content checksum:
  `eee28adc62cbed619bd66047925a0227e18a8f8057421a4282336bb7803ab4c2`.
- Code version checksum:
  `b3d29c826b815e65ad3af2e0d5953c2525b0741ab1ce63994fbdb0ec80cb1282`.
- Provider lineage: 473 unique rows; 472 Yahoo and 1 Tiingo.
- MNST is the Tiingo substitution; VIX and TNX remain Yahoo.
- Structural integrity passed: no future rows, invalid OHLC/volume/indicator
  values, missing latest instruments, or missing latest model fields.
- Exact recent 130-session coverage passed with zero anomalies.

## Promotion blocker — value-level repeatability

Repeated no-write rebuilds produced identical row counts, ticker counts,
provider assignments, and session coverage but different aggregate content
checksums. Observed repeat checksums include:

- `dc8ab4a840e938efb6bd9be0a7549790a28bd4c87697403df7ecd0db85ed0ccb`;
- `60b75a5858abca0ae595bbbd870042aaeec7f55461e907cf446fc60523ad9e99`.

This is a fail-closed blocker. No Friday snapshot may be promoted until the
changing provider rows are isolated and the difference is proven to be either
benign checksum canonicalization noise or a controlled, auditable source-data
revision. Models, recommendations, pending orders, and the sniper must remain
inactive meanwhile.

## Operational state

- `ag-sniper.service`: inactive and disabled.
- `antigravity-nightly.timer`: inactive and disabled.
- `antigravity-qa-watchdog.timer`: inactive and disabled.
- Dashboard service remained available during the recovery checks.
- No model, backtest, exporter, intraday tracker, or order-generation process
  was intentionally activated.

## Next evidence gate

Run a bounded provider-lineage comparison that reports only the changed count
and a small ticker sample, then compare raw values and dtypes for representative
symbols. Promotion remains prohibited until two independent rebuilds are
repeatable under the agreed canonicalization rule.

## Provider repeatability investigation update

The bounded full-universe comparison completed without writes:

- 471/471 controlled instruments accepted; zero rejected.
- MNST replaced completely by Tiingo; zero unresolved session gaps.
- 473 provider-lineage rows present with no missing or unexpected ticker.
- 386–387 stored Yahoo lineages changed across repeated runs.
- The aggregate content hash and provider-lineage hash changed between both
  parallel and sequential full-universe Yahoo pulls.
- Each hash was stable when calculated twice on the same in-memory frame. This
  excludes the checksum implementation as the source of between-run changes.

Direct staged-versus-fresh sample comparison proved that Yahoo raw OHLC changes
were floating-point noise around `1e-14`, while adjusted-close revisions were
widespread and reached approximately `0.00018`. MNST's Tiingo replacement was
exactly unchanged.

Eight representative Tiingo symbols were fetched twice independently: AAPL,
JPM, XOM, NVDA, WMT, XLK, SPY, and IWM. All eight pairs matched exactly in row
count, dtype, value, and SHA-256.

Tiingo's authenticated latest-market bulk endpoint was also tested. The free
account returned HTTP 200 with an upgrade message rather than JSON; the
historical bulk form returned HTTP 400 because Tiingo deprecated it. Therefore
the free plan cannot provide a fast full-universe daily delta in one request.

Provider decision evidence is recorded in
`docs/MARKET_DATA_PROVIDER_DECISION_20260823.md`. A proposed revision-preserving
Turso schema was prepared but not applied:

- Migration: `migrations/20260823_market_eod_revisions_additive.sql`.
- SHA-256:
  `e12c17c87811c1ff39ab032d87a153877e8a89a05fd160d383b313c23f80f9ac`.
- Review-only parser result: four CREATE-only statements; no changes.
- Focused provider/rebuild/migration suite: 31 tests passed.

The leading free third-provider candidate is Alpaca Market Data, pending account
credentials and a complete-universe no-write bake-off. No provider switch,
schema migration, snapshot promotion, model execution, or trading activation
has occurred.

## Alpaca candidate harness verification

An audit-only Alpaca adapter and repeatability harness were added without any
production integration:

- `alpaca_candidate_provider.py` fetches bounded, paginated, fully adjusted
  daily bars and reads credentials only from two one-line secret files.
- `scripts/audit_alpaca_candidate.py` fetches each requested symbol twice and
  reports row, dtype, value, and SHA-256 repeatability without printing
  credentials or writing to Turso.
- `tests/test_alpaca_candidate_provider.py` verifies credential-file handling,
  bounded pagination, adjustment/feed parameters, and secret-safe URLs.
- `tests/test_audit_alpaca_candidate.py` verifies deterministic checksums and
  changed-value detection.

The isolated Vultr recovery suite passed 43 tests. Alpaca remains a candidate,
not a valid production source: no Alpaca credentials were used, no live Alpaca
request was made, and the full-universe/corporate-action bake-off remains open.

## GitHub recovery checkpoint

Repository-scoped GitHub SSH access was restored from Vultr using a dedicated
read/write deploy key. Authentication, `git ls-remote`, and a non-mutating push
dry-run passed before the first recovery commit.

- Repository: `AviShemla/AntiGravity`, branch `master`.
- Recovery commit: `68c66b837cef06240d74d7e52cc3e198bc9172aa`.
- Post-push readback matched the local cloud worktree and remote branch exactly.
- The previously tracked `.env` was removed from the branch head and `.env` is
  now protected by `.gitignore`.
- Fingerprint-only comparison proved the token in the removed public `.env` did
  not match the active Vultr Turso token. No secret value was printed.
- The Vultr Git worktree was clean after push.
- Sniper, nightly, and QA services remained inactive and disabled.

## Resumable EOD writer integrity checkpoint

The revision writer now proves the exact stored `(ticker, date)` keys and
`source_value_sha256` values after every resumable `INSERT OR IGNORE` pass.
A pre-existing run with the expected row count but different stored evidence
fails closed instead of being accepted on count alone. The parent ingestion
run is also created idempotently and then read back: reusing a `run_id` with a
different provider, mode, source session, availability timestamp, code hash,
ticker count, or status is rejected.

- Cloud-focused provider/writer/migration suite: 21 tests passed.
- Python compilation and `git diff --check`: passed.
- GitHub code commits:
  `40a650c77070db2c184a7f5c90f60efc4bd31a7d`.
  `6b6936de2c6849742e2f8f03d29b846efb303a55`.
- GitHub remote readback matched the final code commit exactly.
- No Turso schema was applied and no Turso row was written.
- The Friday snapshot remains `STAGING`; no model, recommendation, order, or
  trading service was activated.
- `ag-sniper.service`, `antigravity-nightly.timer`, and
  `antigravity-qa-watchdog.timer` remained inactive and disabled.

## Owner-approved EOD revision schema application

The owner explicitly approved the reviewed CREATE-only migration with SHA-256
`e12c17c87811c1ff39ab032d87a153877e8a89a05fd160d383b313c23f80f9ac`.
The exact hash was rechecked on the clean Vultr Git worktree before applying
`migrations/20260823_market_eod_revisions_additive.sql` to Turso.

- Applied statements: four CREATE-only statements.
- Created tables: `market_eod_ingestion_runs`,
  `market_eod_bar_revisions`.
- Created indexes: `idx_market_eod_ingestion_runs_lookup`,
  `idx_market_eod_bar_revisions_lookup`.
- Independent Turso readback found all four expected objects and both stored
  table definitions with the required columns.
- Both new tables contained exactly zero rows after creation.
- Core before/after counts were identical: `pending_orders=4`,
  `capital_ledgers=299`, `model_runs=0`, `model_scorecards=0`.
- No market snapshot was promoted and no model, recommendation, pending order,
  ledger entry, or trade was created or changed.
- Temporary audit scripts were verified removed from Vultr.
- Sniper, nightly, and QA services remained inactive and disabled.

## Bounded Tiingo revision-evidence run

With owner authorization to continue, an evidence-only `DAILY_DELTA` run was
executed for source session 2026-08-21. Before any Turso write, each provider
bar was fetched twice independently and required to match exactly.

- Run ID: `tiingo-delta-2026-08-21-audit-v1`.
- Provider: `TIINGO_EOD`.
- Tickers: AAPL, IWM, JPM, NVDA, SPY, WMT, XLK, and XOM.
- Repeatability: all eight provider pairs matched exactly.
- Stored evidence: exactly eight rows, eight distinct tickers, all dated
  2026-08-21, with 64-character source-value hashes.
- Final run status: `COMPLETE`.
- Independent-process Turso readback matched the parent metadata, row count,
  ticker set, session date, and hash lengths.
- Core counts remained `pending_orders=4`, `capital_ledgers=299`,
  `model_runs=0`, and `model_scorecards=0`.
- Focused cloud suite after the final idempotency repair: 25 tests passed.
- GitHub code commits: `f629a5b2e8dc1093ee7ba2cca357779da94464c1`
  and `56cf58776482eb3a484a37826bfaea87fc95f68b`.
- No market snapshot was promoted, no model ran, and no recommendation, order,
  ledger entry, or trade was created or changed.
- Temporary staging/audit scripts were verified removed; sniper, nightly, and
  QA services remained inactive and disabled.

## Full-universe Tiingo evidence staging launched

The resumable full-universe runner was implemented and verified on Vultr
before launch. It writes only provider-native EOD evidence to the additive
revision tables; it cannot promote a model-input snapshot or invoke a model,
broker, recommendation, order, ledger, or trading service.

- No-write Turso preflight: passed.
- Source session: 2026-08-21.
- Universe source: latest validated market snapshot
  `market_features_2026-08-20_3a0e9feffc5ab92f`, followed by lifecycle rules
  and approved registry `etf_registry_20260822_v1`.
- Exact controlled universe: 471 instruments.
- Universe manifest SHA-256:
  `9ee0e6bd3dd34776ea8d7bb79b6eb33c7ca6ed0eeacdaaba38720f58b39e9653`.
- Runner code SHA-256:
  `d6741d15920646533f02fadc874c4958eee7b6883fb431daa47a77453e1f8d93`.
- Run ID:
  `tiingo-delta-2026-08-21-9ee0e6bd3dd3-d6741d159206`.
- Durable rate limit: one request every 76 seconds, with bounded retries.
- Initial live evidence: tickers `A` and `AAPL` staged successfully as rows
  1 and 2 of 471.
- Focused cloud suite: 30 tests passed.
- GitHub commit and remote readback:
  `81ef69dd3b9cd1d43c10ac866b3fd5586a281af4`.
- Execution unit: transient systemd service
  `codex-tiingo-eod-20260821.service`, running with reduced CPU priority.
- `ag-sniper.service`, `antigravity-nightly.timer`, and
  `antigravity-qa-watchdog.timer` remained inactive and disabled at launch.
- The run remains `STAGING` until all 471 exact-session rows are stored and
  the completion gate passes. Snapshot promotion and all downstream model or
  trading actions remain prohibited pending separate owner approval.

## Daily recovery checkpoint — 2026-08-24

Checkpoint time: 2026-08-24T06:01:47.087Z. This was an evidence and recovery
operation only. No market snapshot was promoted, no model ran, no
recommendation or order was created, and no trading service was activated.

### GitHub and cloud worktree

- Repository: `AviShemla/AntiGravity`, branch `master`.
- Pre-check cloud HEAD and GitHub `origin/master` both resolved to
  `cc21af37695c3024079df63dbec2f8a05f083f42`.
- The Vultr worktree was clean and contained no staged files.
- The staged secret-pattern scan reported `NO_STAGED_CHANGES`; no credential
  value was printed or committed.

### Quarantine fresh start evidence

- Implementation commit:
  `5147d922ae45d57e067d11b86ee04921a802df88`.
- Evidence/read-back documentation commit:
  `cc21af37695c3024079df63dbec2f8a05f083f42`.
- Reviewed evidence SHA-256:
  `6082de5547fc380e0cb27a11ce80f7646c47e4556e4dd4d50764200943f2c467`.
- Stock and ETF legacy strike windows restart at source session 2026-08-21;
  historical ledger evidence was not deleted or changed.
- Approved successor registry `etf_registry_20260824_fresh_v2` contains 11
  model candidates, 14 observation/valuation-only instruments, one benchmark,
  and zero quarantined instruments.
- The prior registry remains preserved as `SUPERSEDED`.
- Twenty historical SPY quarantine rows remain preserved.
- Protected counts after readback remained four pending orders, 299 capital
  ledger rows, zero new model runs, and zero new model scorecards.

### Verification

- Focused quarantine-policy suite: seven tests passed, zero failed.
- `ag-sniper.service`: inactive and disabled.
- `antigravity-nightly.timer`: inactive and disabled.
- `antigravity-qa-watchdog.timer`: inactive and disabled.
- Production use of CSV, Excel, SQLite, and Streamlit was not introduced.
