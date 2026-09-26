# Oracle research data architecture: checkpoint update

The working nightly extraction is unchanged. This document describes research
components added alongside it, not a replacement runtime or trading system.

```text
Nightly extraction -> accumulated market_feature_history
                                 |
                       approved W1 membership
                                 |
          retained frozen August base + compressed cell differences
                                 |
              frozen W2 version and content manifest
                                 |
                  hash-bound read-only selector
                       /                     \
       corrected W3 baselines         W4 stock input adapter
       dated predictions saved        existing dataset builder
                                      input fixture passed only
```

## Component map

| Component | Artifact / persistence | State |
| --- | --- | --- |
| W1 membership | ORACLE_W1_GOVERNED_UNIVERSE_2026-09-25.json | Approved 474-instrument membership |
| W2 retained base | market_daily_features; existing frozen August snapshot | Reused, not copied |
| W2 overlay | oracle_w2_content_versions and oracle_w2_content_patches in existing isolated Turso database | FROZEN after reconstruction |
| W2 reconstruction | oracle_w2_content_version.py | Base and delta content hashes checked by reader |
| W2 selector | oracle_w2_selector_reader.py and ORACLE_W2_RESEARCH_INPUT_SELECTOR_2026-09-25.json | Bound to frozen version, not mutable history |
| W3 evaluator | oracle_w3_current_baselines.py | Corrected per-target lag, fit once per fold |
| W3 output | ORACLE_W3_CORRECTED_RESULTS_2026-09-26.json; per-instrument artifacts on Vultr | Completed, limitations explicit |
| W4 adapter | oracle_w4_frozen_input.py | Input-only fixture passed; no approved current chain or fitted model |

The saved oracle_w3_baseline_bridge.py is an earlier interface for an evaluator
exporting evaluate_ticker; it was NOT the entry point of the corrected W3 run.
Do not treat its presence as proof that it is connected.

No point-in-time historical-data claim, predictive superiority, causal
identification, production promotion or trading authority follows from this
checkpoint. The broader migration plan and proposed registry retain their
separate authority and acceptance requirements.
