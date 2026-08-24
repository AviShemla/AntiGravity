# Stock Research Feature Layer — Verified State (2026-08-24)

## Scope and safety state

This change is research-only. It does not run PyMC, alter eligibility policy,
promote a universe, create recommendations or orders, or activate a service.
All features are computed from a governed point-in-time market snapshot and are
lagged one completed session before use as predictors.

## Implemented feature families

### Predictive network structure and stability

- Independently selected `(driver ticker, target-relative lag)` edges are
  summarized across outer walk-forward folds.
- Edge evidence records the number and fraction of folds selecting the exact
  ticker/lag pair.
- Node evidence reports stability-weighted incoming and outgoing importance.
- The evidence is named **predictive**, not causal: observational selection
  stability alone does not identify a causal effect.

### Market breadth and dispersion

- Fraction of instruments advancing.
- Fraction of total volume in advancing instruments.
- Fraction of instruments above their 20-session moving average.
- Cross-sectional return dispersion.
- Fraction of sectors with positive mean return.

### Volatility regime and available term evidence

- One-session VIX change.
- One-session VIX acceleration.
- Five-session VIX change.
- Annualized 20-session SPY realized volatility.
- VIX minus SPY realized volatility.

True term-structure and volatility-of-volatility features are fail-closed. They
are emitted only when explicit point-in-time `VIX9D`, `VIX3M`, `VVIX`, or
`SKEW` source columns exist. `VIX_Close` is never used as a fabricated
substitute for a missing series.

## Turso readback evidence

The read-only audit used validated snapshot
`market_features_2026-08-21_eee28adc62cbed61`:

- Source session: `2026-08-21`
- Input rows: `582,798`
- Input instruments: `471`
- Derived feature sessions: `1,244`
- Derived feature count: `10`
- Latest-session feature values: all finite
- Unavailable governed source series: `VIX9D`, `VIX3M`, `VVIX`, `SKEW`

## Remaining gates

1. Define and approve an additive Turso lineage schema for derived research
   feature evidence.
2. Ingest and license-check any missing volatility series before enabling their
   derived features.
3. Compare the exact AG stock admission conditions from the deployed SPY/stock
   scripts with proposed Codex evidence gates.
4. Preregister the selected research feature contract before a new screening
   run; do not select features from outer test results.
5. Keep raw posterior predictions separate from eligibility and execution.
