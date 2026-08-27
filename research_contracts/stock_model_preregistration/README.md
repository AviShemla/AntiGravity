# Successor hierarchical stock model preflight

This isolated package is a fixture-only preregistration contract. It does not
read Turso, fit a model, or emit predictions, recommendations, orders, or ETF
artifacts.

Integration sequence after review:

1. Import the module into the canonical repository as an additive artifact.
2. Replace fixture identities with independently read, immutable snapshot,
   universe, full-baseline audit, Git, model-config, and sampler identities.
3. Generate and persist the preregistration once, before any fit is authorized.
4. Independently recompute the baseline-audit evidence digest, then replay all
   semantic validators (not merely the outer manifest digest).
5. Freeze the governed four-fold geometry: 289-session training intervals,
   30-session outer tests, 30-session steps, seven-session purge, and a
   126-observation minimum. The exact calendar ordinals `0..415` are content-hashed;
   every supplied fold must equal the resulting geometry and outer tests may
   never overlap.
6. Use explicit `NEW_RUN` or `RESUME` mode. A resume must present both the
   unchanged prior manifest and its identical checkpoint identity; any restart
   or deployment mismatch fails closed. Immutable audit provenance remains in
   that identity, while every new audit or resume must separately provide a
   fresh readback proof matching the immutable audit and baseline identities;
   its timestamp must follow both immutable audit completion and observation.
7. Keep all prediction, recommendation, order, trading, and ETF paths disabled
   until their separately governed evidence stages are approved.

The wording is intentionally observational: independent ticker/lag edges are
predictive-association hypotheses, never causal proof.
