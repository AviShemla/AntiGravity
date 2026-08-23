# Market-data provider decision evidence — 2026-08-23

Status: investigation complete enough to reject Yahoo as the sole canonical
model-input source. No production provider switch has been activated.

## Measured evidence

- Four full, no-write Friday rebuilds retained identical universe size,
  session coverage, and provider assignments but produced different content and
  provider-lineage checksums.
- The hash is deterministic inside one process; calling it twice on the same
  frame returns the same value.
- Both parallel and sequential full-universe Yahoo pulls changed between runs.
- Direct staged-versus-fresh comparison found:
  - raw Yahoo OHLC differences around floating-point epsilon (`1e-14`);
  - widespread Yahoo adjusted-close revisions up to approximately `0.00018` in
    the bounded sample;
  - no corresponding date or row loss.
- Eight representative Tiingo symbols (AAPL, JPM, XOM, NVDA, WMT, XLK, SPY,
  and IWM) were fetched twice. Every pair had identical rows, dtypes, values,
  and source checksum.
- MNST's complete Tiingo replacement matched its staged raw market values
  exactly.

## Provider constraints proven from official documentation

Tiingo documents a correction-aware EOD feed with raw and adjusted OHLC,
volume, dividends, and splits. It states that corrections can arrive through
20:00 US Eastern time. Its free Starter quota is 500 unique symbols/month, 50
requests/hour, 1,000 requests/day, and 1 GB/month:

- https://www.tiingo.com/documentation/end-of-day
- https://www.tiingo.com/about/pricing

The free quota covers this controlled universe, but a 471-symbol per-ticker
refresh requires roughly 9.5 hours at the published hourly limit. Tiingo's
documented latest-market bulk endpoint would make daily deltas efficient, but
an authenticated VPS probe returned a successful HTML response stating that
the full market snapshot is restricted to the Power plan. The deprecated
historical bulk form returned HTTP 400. Therefore the free plan cannot be the
only fast nightly source.

Alpaca's free Basic market-data plan is the leading third-provider candidate.
Official documentation advertises US stocks/ETFs, history since 2016, 200
historical requests/minute, multi-symbol historical bars, adjustment modes
including `all`, and a separate paginated corporate-actions endpoint:

- https://docs.alpaca.markets/us/docs/about-market-data-api
- https://docs.alpaca.markets/us/v1.4.2/reference/stockbars
- https://docs.alpaca.markets/us/reference/corporateactions-1

Alpha Vantage is not suitable as the free primary source because its Daily
Adjusted endpoint is documented as premium. Polygon was not selected because
the available official evidence did not establish a free plan satisfying the
required five-year adjusted history and full-universe quota.

## Recommended architecture

1. Use Alpaca adjusted multi-symbol daily bars as the fast primary candidate,
   pending credentialed bake-off and complete-universe proof.
2. Use Tiingo EOD as the correction/corporate-action authority and independent
   verifier. Bootstrap the complete Tiingo history once under its published
   rate limits; refresh only affected histories when a dividend or split is
   observed.
3. Retain Yahoo only as a non-authoritative emergency comparator. A Yahoo-only
   snapshot cannot pass the repeatability gate demonstrated above.
4. Store all raw observations and revisions in Turso. No CSV, Excel, SQLite, or
   local market-data cache may participate.
5. Start EOD ingestion only after the provider correction window. For Tiingo,
   schedule after 20:00 US Eastern plus a safety margin, not at 01:00 Israel
   time.
6. Require two independent, identical canonical rebuild hashes before a market
   snapshot can be eligible for model use.
7. Keep provider acquisition, model execution, recommendation creation, order
   staging, and sniper consumption as separate approval-gated states.

## Current decision

The corrected Friday snapshot remains `STAGING`. It is not eligible for models
or orders. The next implementation step is an additive, revision-preserving
Turso raw-bar schema plus credentialed Alpaca/Tiingo ingestion tests. Schema
application and provider activation remain separate explicit decisions.

## Candidate implementation status

The Alpaca integration is still audit-only. A bounded adjusted-bars adapter and
repeatability audit now exist, and the isolated recovery suite passes 43 tests.
No credentials, production wiring, Turso writes, or provider activation have
occurred. Alpaca can be classified as valid only after a credentialed
full-universe repeatability, coverage, adjustment, and corporate-action audit.
