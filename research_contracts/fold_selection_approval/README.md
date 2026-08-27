# Fold-selection approval proposal

This package produces a deterministic, reviewable proposal for the governed
four-fold stock edge-selection evaluation. It can deterministically compute
research selections only from a complete, injected, panel-bound evidence
stream. It cannot authorize, deploy, persist, or initiate a selection run,
model, prediction, recommendation, order, or database write.

`s08_selector_v7.py` is an inert, selection-only research proposal and replay
auditor. It supplies no execution or authorization API; possessing a result is
insufficient without complete panel-bound source-evidence replay.

`training_fold_selection_approval_v5.py` is the reviewed public proposal
surface. Its trust root is deliberately absent, so every preflight returns
`APPROVAL_REQUIRED` with zero selections. The v4 module is retained only as an
internal artifact builder used by v5 and is not approval-ready on its own.

The v5 proposal binds the exact 474-ticker lineage, snapshot SHA-256, frozen
calendar bytes, dated 289/7/30 train/purge/test geometry, complete
TARGET_ASC_SOURCE_ASC_LAG_ASC candidate enumeration, selector/verifier bytes,
dependency lock, evidence contract, policy, and resource-estimation contract.

Execution requires a future, separately reviewed canonical trust-root and
execution gate after Avi approves the exact generated proposal hashes and
wording. A fresh independent frozen-dataset readback no older than 300 seconds
must still pass at that future execution boundary.
