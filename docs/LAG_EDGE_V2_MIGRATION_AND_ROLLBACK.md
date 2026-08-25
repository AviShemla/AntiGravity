# Lag-edge v2 migration and rollback contract

Status: review-only; not applied to production Turso.

## Scope

The v2 schema separates chain depth from per-edge lag. A chain has 1 through 5
ordered predictor edges; each edge independently declares 1 through 7 target-
relative trading sessions. Lag order need not be consecutive or monotonic.
Screening evidence freezes first. A stock-universe edge set can freeze only
when it exactly equals the referenced frozen screening edge set.

The schema is additive. Legacy positional lag columns remain untouched and
must not be used by the future v2 read path after v2 activation.

## Atomic application

'scripts/apply_atomic_migration.py' parses explicit statement markers instead
of splitting on semicolons. It sends BEGIN IMMEDIATE, every reviewed DDL
statement, an append-only migration-ledger event, and COMMIT in one Turso
pipeline request. Exact migration bytes must match the reviewed SHA-256.
Check-only is the default. Apply additionally requires event, actor, explicit
target database identity, and evidence JSON. This document grants no production
application authority.

## Required isolated Turso matrix

Before production approval, run the exact hash-pinned bundle on a disposable
Turso branch and independently prove:

1. depths 1 and 5 and lags 1 and 7 are accepted;
2. depth 0 or 6 and lag 0 or 8 are rejected;
3. insertion into a frozen set is rejected;
4. edge update and delete are rejected;
5. missing or non-dense edges block screening freeze;
6. an unfrozen screening source blocks universe freeze;
7. one differing edge blocks universe freeze;
8. exact equality permits the single DRAFT-to-FROZEN transition;
9. further header updates and every delete are rejected;
10. a deliberately failing DDL rolls back all earlier DDL and the ledger event.

Record branch identity, artifact SHA-256, event ids, scoped sqlite_master object
hashes, and ledger readback. Never run this matrix against production.

## Rollback

Rollback is logical and non-destructive:

1. stop v2 writers and prove no v2 research run is active;
2. append one ROLLBACK event referencing the APPLY event;
3. make v2 readers fail closed when the latest event is ROLLBACK;
4. verify legacy readers remain unchanged;
5. retain v2 tables and events as forensic evidence.

Dropping tables, deleting ledger events, or rewriting edges is not an authorized
rollback. A correction is a new hash-pinned migration version. Production apply
or rollback requires explicit owner approval and independent readback.
