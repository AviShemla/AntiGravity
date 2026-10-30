# W2 immutable content version: complete

- Version: oracle-w2-20260925-delta-v1
- Turso state: FROZEN, confirmed by terminal readback.
- Reconstruction: PASS, 597139 rows, 474 instruments, 34 selected columns.
- New rows retained: 10429.
- Corrected cells retained: 1458657.
- Compressed delta payload: 17573660 bytes (not total billed database storage).
- Manifest SHA-256: fbfc4cbf4426b7b27cf312fd4fc57eea505cae1366262a6ff952f56250882be1.
- Reader selector is bound to the saved immutable version, not live history.
- Existing August data reused; no full-history copy or source-table writes.
- Nightly extraction, schedules, watchdog, and trading unchanged.
- Operational created_at_utc is excluded from the 34 model columns.
- This freezes currently observed data; historical point-in-time availability is not proven.
- W3 scientific baseline acceptance remains separate and incomplete.

Lessons applied: ORA-INC-004, 008, 018, 039, 045, 046.