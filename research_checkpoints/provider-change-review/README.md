# Preserved changes: review only

These patch files are NOT applied, deployed, tested, or approved for execution.

- original-provider-change.patch preserves the existing working-copy provider changes.
- vix-only-proposed.patch isolates the VIX placeholder filter while retaining explicit zero OHLC tolerance for Yahoo and Tiingo.
- ohlc-relaxation-separated-NOT-APPROVED.patch isolates the removed strict validation. Do not apply it.
- authorization-deletion-NOT-APPROVED.patch preserves the pending deletion for investigation. The authorization file is neither deleted nor restored by this checkpoint.

The VIX candidate still requires review of calendar coverage and its caller before implementation. No runtime-readiness claim is made.
The existing Vultr working-copy changes are intentionally untouched. Nightly code, timers, services, databases, and trading are unchanged.
