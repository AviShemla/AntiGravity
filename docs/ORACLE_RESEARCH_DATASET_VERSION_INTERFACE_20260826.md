# Oracle research dataset version interface — 2026-08-26

Stage: **IMPLEMENTED** locally; production schema remains **NOT APPLIED**.

## Purpose

`oracle_research_dataset.py` defines a read-only, fail-closed interface for one
exact frozen Turso research dataset version. `oracle_research_dataset_writer.py`
defines a pure, injected transaction contract for staging and freezing. Neither
module owns a connection, credentials, schema application, validation,
promotion, revocation, or production execution path.

The caller must provide the expected market snapshot ID, lowercase SHA-256,
source session, research dataset version ID, and point-in-time cutoff. The
reader reconciles those values against:

- the frozen dataset version and its latest append-only event;
- the bound `MARKET_FEATURES` snapshot metadata;
- exact row, ticker, session, first-session, and last-session counts;
- exact per-symbol Yahoo/Tiingo provider lineage and source checksums; and
- content and ticker-universe digest binding between the version and freeze
  event; and
- an independently recomputed provider-lineage digest compared with the
  version and freeze event.

Content and ticker-universe digests are not independently recomputed by this
reader. They remain event/version binding evidence until an approved canonical
row serializer is implemented and tested. Reports must not describe those two
bindings as independent content verification.

Provider lineage does have one implemented canonical serialization: records
are sorted by ticker and encoded as compact UTF-8 JSON Lines arrays containing
`ticker`, `provider`, requested source session, first/last available dates,
source row count, and lowercase source SHA-256, with exactly one final LF byte.
The reader computes SHA-256 over those bytes and fails closed on disagreement.

Any missing identity, checksum mismatch, count drift, provider drift,
revocation, invalid chronology, or non-frozen status raises `LineageError`.

## Review-only schema artifact

`migrations/20260826_oracle_research_dataset_versions_additive.sql` is additive
and contains no data writes. It declares:

1. version metadata with exact snapshot/checksum/session/count lineage;
2. the frozen per-symbol provider binding;
3. append-only freeze/revoke evidence; and
4. database-edge triggers that prevent mutation of frozen version metadata,
   bound market rows, snapshot metadata, and provider lineage.

The migration must not be applied merely because code tests pass. Production
application requires Avi's explicit schema approval plus a reviewed,
hash-locked execution plan, an approved idempotent writer, a freeze transaction
contract, pre/post Turso schema readback, and a rollback/incident plan. Dataset
freezing is a separate approval from schema application.

The behavioral migration tests use only a standard-library `:memory:` SQL
connection with minimal source-table stubs. This is a test-only Turso-compatible
DDL/trigger check: it creates no database file, uses no credentials or network,
and is not an application or production fallback.

## Implemented write-order contract

The writer accepts only an injected immediate transaction runner. Within that
boundary it independently verifies the exact validated market snapshot,
checksum, row/ticker/session coverage, cutoff chronology, and canonical
provider-lineage digest. Staging can create only `STAGING`, copies exact
provider bindings without changing any source table, and reads the complete
result back before commit.

Freezing requires explicit event ID, actor, decision time, evidence checksum,
and all four matching identity hashes. The event append and conditional
`STAGING` to `FROZEN` transition occur in one transaction, followed by exact
readback through that same transaction. Exact retries return the existing
result; conflicting retries fail closed. If an adapter reports an ambiguous
commit result, the writer accepts success only after an independent exact
readback. A later revocation remains an append-only event and is outside this
writer.

The contract is implemented and dependency-free tested, but no production
transaction adapter is provided. Connecting it to Turso or another production
database, applying the schema, staging data, and freezing data each remain
separately approval-gated operations.

## Current rollback boundary

Nothing is deployed or applied. Before merge, rollback is deletion of these
new, uncommitted code artifacts. After any future schema application, rollback
must not drop evidence tables or frozen rows; the approved incident procedure
must leave them intact and disable the unapproved writer/read path instead.
