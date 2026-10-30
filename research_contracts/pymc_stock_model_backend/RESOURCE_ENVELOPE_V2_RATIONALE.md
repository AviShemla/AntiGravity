# S08 resource-bounded execution contract v2

This is a fixture-only planning contract. It does not authorize or launch a
run.

- The observed same-science elapsed time is exactly 7,425 seconds. The runtime
  limit is derived mechanically as 125% rounded upward to one minute: 9,300
  seconds. It is not a caller-selected relaxation.
- CPU quota is bound to the authoritative v6 systemd readback of exactly 200%
  (`CPUQuotaPerSecUSec=2s`). It is never rewritten to 50%. Capacity is a
  separate decision: 200% research plus fixed 100% ingestion and 100% host
  reservations requires 400% total capacity, so the current 3-CPU/300% host is
  classified `RESOURCE_BLOCKED`.
- Memory is bound to the authoritative v6 `MemoryPeak=1404485632` bytes, then
  receives 25% headroom rounded upward to 64 MiB. It must fit
  while retaining at least 2 GiB for guarded ingestion and 1 GiB for the host.
- The next ingestion must remain later than the full 9,300-second envelope plus
  an additional one-hour buffer. Active ingestion, stale capacity, a duplicate
  worker, or an absent priority reservation fails closed.
- The v6 sampler was silent after initialization and produced no durable
  progress/checkpoint markers. Its maximum checkpoint gap is therefore
  `UNKNOWN` (`None`), never 600 seconds. Every plan from this evidence carries
  the fail-closed `DURABLE_PROGRESS_UNOBSERVED` blocker until a separately
  hash-bound observation series exists.
- Four chains, 1,000 draws, 1,000 tune, R-hat <= 1.01, bulk/tail ESS >= 400,
  BFMI >= 0.3, zero divergences, and tree-depth fraction <= 0.01 are exact and
  cannot be weakened through plan inputs.
- Database writes, downstream outputs, and execution authorization remain
  false. A separate explicit run authorization and launcher contract would
  still be required.

The measurement identity also binds InvocationID
`e8a9f0c2b3834aaf88c3ffbd333a77a6`, CPUUsageNSec `14782971921000`, and exit
status `1`, with systemd start `2026-08-27T12:52:22Z` and exit
`2026-08-27T14:58:32Z`. The 7,425-second application measurement remains a
separate bound field and is not falsely recomputed from unit lifecycle time.
The contract represents the measured resource shape; it does not
misstate that terminal measurement as a successful scientific run.
