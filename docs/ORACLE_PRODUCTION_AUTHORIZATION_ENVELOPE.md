# Non-circular Oracle production authorization envelope

Status: local design and fixture-tested reference only. Nothing here is
deployed or production-authorized.

## Problem

The production adapter pinned one concrete application-contract SHA-256, while
the reviewed application contract pinned the adapter byte SHA-256. Any change
to either leaf changed the other leaf's hash, so the two-artifact trust graph
was circular and could never reach a stable, internally consistent state.

## Smallest trust graph

The replacement is a one-way envelope:

```text
non-circular reviewed application contract ─┐
                                             ├─> canonical envelope SHA-256
immutable adapter release manifest ─────────┘             │
                                                          ▼
                                  explicit scoped approval or immutable launcher
```

The application contract pins only the envelope protocol ID and explicitly
forbids a concrete adapter hash. The adapter release pins the adapter and gate
bytes in one canonical immutable manifest. Only after both leaves are final is
the envelope assembled. Runtime receives the expected envelope SHA-256 from an
independent trusted approval or immutable launcher; it must never accept the
hash claimed by the envelope itself as its trust root.

The envelope binds the application-contract hash, adapter release-manifest
hash, adapter entrypoint hash, exact Turso database ID, content-audit evidence,
two allowed dataset operations, and zero model/trading outputs. The separate
runtime authorization binds one envelope, validity interval, actor, exact
dataset/freeze identities, and two distinct schema/freeze approvals.

## Integration recommendation

1. Keep HEAD `7c7f765` production-disabled. The `854a…` adapter pin versus
   reviewed `127f…` contract is a stop-the-line contradiction.
2. Create a new reviewed application-contract revision that uses the exact
   `authorization_binding` defined here and removes the concrete adapter hash.
   Do not edit or reinterpret the already reviewed `127f…` bytes.
3. Integrate this verifier into the adapter, finalize the complete immutable
   adapter release (adapter plus verifier), and independently verify its
   release manifest.
4. Assemble the canonical envelope only after steps 2–3. Independently review
   and publish its SHA-256 in the separately scoped explicit authorization or
   immutable launcher configuration.
5. At runtime, re-read the contract, complete adapter release, envelope, and
   approval; require every hash and scope to match before constructing any
   transport. A failure performs zero network/database calls.
6. Treat changing the contract, adapter release, envelope, or approval as a
   new review and authorization. Never regenerate a neighboring hash inside an
   existing approval.

This design does not approve schema application or dataset freeze. Those still
require their two distinct explicit approvals and all existing readback gates.

## Deterministic v2 contract revision

`application_contract_v2.py` transforms only the exact hash-verified reviewed
v1 contract. It preserves every unrelated v1 field, evidence object, and
artifact descriptor. It replaces only the concrete injected-adapter descriptor,
adds the exact protocol-only `authorization_binding`, records revision 2 and
the superseded v1 contract ID/SHA-256, and appends envelope and envelope-bound
approval blockers to both schema and freeze readiness. Both executable flags
must already be false and remain false. Output is deterministic canonical JSON;
the original v1 mapping is never mutated.

## Minimal adapter integration

`adapter_integration_reference.py` demonstrates the required ordering. The
production adapter change should be limited to:

1. delete the embedded `_CONTRACT_SHA256` constant and the old direct
   `authorization.contract_sha256 == constant` comparison;
2. replace that authorization field with `envelope_sha256`;
3. accept an unconstructed injected `transport_factory`, the canonical
   envelope and explicit authorization, the externally trusted expected
   envelope SHA-256, and the read-only contract/release paths;
4. call `validate_runtime_authorization` before invoking the transport factory;
5. retain every existing target-database, approval-separation, operation-ID,
   SQL allowlist, atomic transaction, rollback, and zero-output gate unchanged.

The verifier and adapter must be finalized in the same immutable release. The
envelope then pins that complete release manifest. The expected envelope hash
must still come from the separate explicit approval or immutable launcher—never
from adapter source, the application contract, or the envelope itself. This
removes the embedded contract hash without weakening runtime trust.
