# Frozen stock and ETF statistical validation gates

Status: **research-review only**. These gates do not run models, approve data,
promote scorecards, size a live portfolio, create orders, or activate services.

## Statistical principle

The stock and ETF models remain Bayesian stochastic models. Their posterior
means, intervals, expected-return distributions, predictive risk and sampler
diagnostics must remain visible even when a downstream gate fails. A gate does
not make the model deterministic and does not rewrite a posterior. It answers
only:

1. Is the evidence sufficiently trustworthy to consider shadow sizing?
2. Should comparative evidence reduce that shadow sizing?
3. Which exact measurement caused a failure or warning?

## Frozen measurable review policy

These values are an explicit starting policy for controlled evaluation, not
approved production thresholds.

| Review area | Type | Measurable gate |
|---|---|---|
| PyMC convergence | Hard | at least 2 chains; R-hat <= 1.05; bulk ESS >= 200; tail ESS >= 100; E-BFMI >= 0.20; zero divergences; tree-depth saturation <= 1% |
| Walk-forward/OOS | Hard | at least 3 folds, 30 OOS observations, at least 1 embargo session and zero train/test overlap |
| Calibration | Hard | Brier score and log loss must both beat the recorded naive baseline; expected calibration error <= 0.10 |
| Immutable lineage | Hard | exact market snapshot, universe snapshot and model run IDs; aligned source session; matching input checksums; point-in-time features; complete provider lineage |
| ETF stock prior | Hard for ETF | complete audited stock direction/return prior lineage from one frozen stock run |
| Costs and drawdown | Hard | gross return minus recorded transaction costs must exactly reconcile to net return; stress net return > 0 percentage points; maximum drawdown <= 20 percentage points |
| Simple baseline | Sizing | model net return must beat the simple baseline net return |
| Arena median | Sizing | model net return must be at least the Arena median and model drawdown no worse than the Arena median |

The initial 30-observation OOS gate deliberately avoids imposing a 252-session
eligibility requirement. It supports the requested recent-window investigation
while still requiring multiple embargoed folds. Horizon/window selection must
be re-evaluated separately and must never be selected on the same OOS sample
used to report performance.

## Hard gates versus sizing evidence

Hard-gate failure sets shadow-sizing eligibility to false and the multiplier to
zero, but raw posterior evidence remains visible.

Simple-baseline and Arena misses do **not** erase an otherwise valid prediction.
They are sizing warnings:

- no comparative warnings: multiplier 1.00;
- one warning: multiplier 0.50;
- two warnings: multiplier 0.25.

These multipliers are research hypotheses only. They are not an instruction to
trade and cannot bypass the separate promotion, broker, capital, market-hours,
or sniper controls.

## AG versus Codex per-prediction table

The package appends two rows to the existing AG / strict Codex / balanced
comparison table:

1. **Statistical validation** — AG is shown as UNPROVEN where the repository
   does not prove equivalent controls; Codex reports exact convergence,
   walk-forward, calibration, lineage, and cost/drawdown results.
2. **Baseline and Arena sizing** — AG is shown as UNPROVEN; Codex reports the
   measured warning reasons and research-only multiplier.

The original rows remain intact, including:

- raw Bayesian output;
- hard evidence gates;
- direction strength;
- Kelly sizing;
- VIX sizing;
- operational safety.

Therefore every prediction can be reviewed without being silently discarded.
The table separates model evidence, statistical validation, policy eligibility,
sizing and execution controls.

## Required evidence records

For each stock and ETF review, the evaluator requires already-computed,
point-in-time evidence:

- immutable snapshot/run/checksum IDs;
- SamplerDiagnostics;
- fold count, OOS count, embargo and overlap count;
- model and naive Brier/log-loss plus expected calibration error;
- gross return, transaction cost, net/stress return, turnover and drawdown;
- simple-baseline and Arena-median net return/drawdown;
- posterior probability mean/interval, expected return and predictive risk.

Canonical units remain:

- probabilities, weights, turnover and allocation: fractions;
- return, risk, costs after conversion and drawdown: percentage points;
- raw transaction-cost inputs at their ingestion boundary: basis points.

The evaluator is pure Python and has no prohibited file-data, embedded-database,
dashboard-framework, network, database-write, model-fitting,
recommendation-promotion, order or service path.
