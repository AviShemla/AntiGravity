# Independent-edge hierarchical stock-model boundary

This isolated, synthetic-only implementation replaces the legacy positional
`lag1_ticker`/`lag2_ticker` chain assumption with independently tested
`(source ticker, target ticker, lag)` edges over exact lags 1–7. Selected depth
is the number of globally BH-FDR-qualified edges retained for a target, capped
at five; it is not a forced 5→4→3 chain and edge lags need not be consecutive or
monotone.

The selector uses only rows at or before an explicit training cutoff. It emits
an immutable artifact containing every hypothesis, p-value, BH q-value, aligned
sample count, and selected edge. The claim is observational predictive
association, never causal proof.

The fit-request builder uses the current canonical percentage interface:
`y_return_pct`, `expected_return_pct_mean`, `expected_return_pct_std`, and
`predictive_risk_pct`. It creates one standardized matrix per target and a
partial-pooling graph boundary. A backend must be explicitly injected; this
package does not import or choose PyMC and does not fit real data.

Backend output is accepted only with exact target coverage, canonical percent
fields, four chains, at least 1,000 tune and 1,000 posterior draws, strict
diagnostics, and zero database/prediction/recommendation/order/ETF/trading side
effects. Results remain research-only and operationally ineligible.
