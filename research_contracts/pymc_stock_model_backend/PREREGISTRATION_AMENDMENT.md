# S08 convergence-recovery preregistration amendment candidate

Status: **IMPLEMENTED / STRUCTURALLY TESTED / EXECUTION NOT AUTHORIZED**.
Independent review and Avi's explicit approval of the new model-config hash are
required before any sampler or real fit may execute.

## Evidence basis

V6 failure evidence SHA-256
`aa2100860767421576dde2947d0ab78e827e91c2108631786db1ff12f60e5602`
binds run-log SHA-256
`b98b4d2f5d442889a4e43a9f5888986585025e02f898a360d87fbcb39bc117b4`.
Sampling completed all four chains with 1,000 tune plus 1,000 retained draws
per chain in 7,425 seconds. All four chains hit maximum tree depth, some R-hat
values exceeded 1.01, and ESS per chain was below 100. Exact R-hat and ESS
extrema are unavailable and remain `UNKNOWN`; they are not reconstructed.

Three failures remain deliberately distinct:

1. **Scientific convergence failed:** the preserved warnings violate the
   unchanged tree-depth, R-hat, and ESS gates.
2. **Progress telemetry was absent:** sampling completed, but no durable
   checkpoint/progress series exists, so maximum checkpoint gap is `UNKNOWN`.
3. **Terminal postprocessing failed:** the terminal diagnostic path failed on
   ArviZ `DataTree` extraction and the unit exited status `1`; this does not
   mean sampling failed to complete.

Measured resources are separately bound: `CPUQuota=200%`,
`MemoryPeak=1404485632`, `CPUUsageNSec=14782971921000`, systemd start
`2026-08-27T12:52:22Z`, and exit `2026-08-27T14:58:32Z`. The observed
hierarchical sampling failures scientifically motivate evaluating a
distribution-preserving non-centered form, but do not identify one unique
cause and do not prove the candidate will converge.
A separately authorized synthetic four-chain evaluation must pass every
unchanged gate.

## Exact amendment

The four centered group effects become non-centered transforms:

- `direction_alpha = direction_alpha_mu + direction_alpha_scale * direction_alpha_raw`
- `direction_beta = direction_beta_mu + direction_beta_scale * direction_beta_raw`
- `return_alpha = return_alpha_mu_pct + return_alpha_scale_pct * return_alpha_raw`
- `return_beta = return_beta_mu + return_beta_scale * return_beta_raw`

Each new `*_raw` latent has `Normal(0, 1)`. Conditional on the unchanged
location and scale hyperparameters, these transformations induce exactly the
same Normal priors as v1. **Changed priors: none.** The HalfNormal scale priors,
return `HalfNormal(2)` noise prior, and `2 + Exponential(0.1)` Student-t degrees
of-freedom prior are unchanged.

## Preserved boundaries

Data, outcomes, training-only scaling, Bernoulli-logit direction target,
Student-t percentage-return target, independent ticker/source/lag edges,
lags 1–7, depth 1–5, no positional chain, no causal claim, four chains,
1,000 tune, 1,000 draws, and all R-hat/ESS/BFMI/divergence/tree-depth gates are
unchanged. No database write, posterior persistence, recommendation, ETF,
order, trading, deployment, or sampler path exists in this isolated candidate.

## Required successor gates

1. Independent code/scientific review and explicit approval of the amended
   content-addressed model identity.
2. A separately authorized, resource-safe synthetic four-chain run with
   durable progress observation.
3. Independent terminal diagnostic audit against the unchanged gates.
4. Only then may a distinct real-fit authorization be considered.

