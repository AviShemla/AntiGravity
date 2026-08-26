# Hierarchical stock model preregistration  2026-08-26

Status: **DESIGNED / IMPLEMENTED, not yet TESTED, DEPLOYED, OBSERVED, or VERIFIED**.

## Authority and safety boundary

This is a research-only extension to the frozen stock workflow. It does not authorize
snapshot validation or promotion, model-input approval, recommendations, orders,
email, trading, ETF priors, or sniper activation. Existing safety gates remain
unchanged. Rollback is the additive commit's Git revert.

## Frozen evidence and hypothesis

The 60-, 126-, and 252-session screening contracts completed, while 30 sessions was
preflight-rejected by the governed minimum-data rule. No screened candidate cleared
the frozen uncertainty gate. The development evidence therefore does not justify a
trade or a production model.

The registered research hypothesis is narrower: non-centred partial pooling across
targets may reduce estimation variance while retaining independently selected
ticker/lag edges. It is not causal proof.

## Model contract

- Inputs are immutable, validated Turso-backed `StockModelDataset` artifacts.
- Each target retains one to five independently screened edges at lags 17.
- There is no forced 5𗮹 chain and no fabricated edge for absent depth.
- Direction uses a hierarchical Bernoulli-logit head.
- Return uses a hierarchical robust Student-t head.
- Target intercepts and edge-slot coefficients are partially pooled.
- Posterior uncertainty and sampler diagnostics are mandatory outputs.

## Anti-selection and evaluation

The existing screening results are development evidence only. Model selection and
threshold tuning must not reuse their evaluation folds as final confirmation.
Required future evidence is an untouched or prospective cohort with purged
walk-forward folds, baseline comparison, convergence, calibration, transaction-cost,
and drawdown checks. Failure of any frozen gate yields NO_TRADE.

## Required per-prediction record

Every eventual prediction must preserve: raw Bayesian output; inherited AG decision
and reasons; proposed Codex decision and reasons; hard safety gates; sizing
adjustments; snapshot, code, screening-run, model-run, and sampler lineage.

## ETF boundary

ETF priors remain forbidden until stock evidence passes the registered confirmation
and governance gates. Posterior evidence must remain auditable and reversible.
