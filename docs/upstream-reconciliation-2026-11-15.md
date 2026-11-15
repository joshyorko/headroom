# Self-hosted upstream reconciliation and T3 hub reporting

## Reconciliation boundary

- Starting fork: `9eaf50a1a93aaceb8c39af5304ce3fab0289f5c1`.
- Upstream main: `5023c84e527e28281dd73d1ba04184fe738aac0f` (43 new commits).
- Merge work is isolated from the primary checkout's unrelated dirty files.
- The November 11 preservation ledger remains the fork behavior baseline.

Conflict resolutions retain the fork's deleted PR-health/security workflows,
take upstream's added read-lifecycle tests, and combine the fork's same-origin
settings-write ordering with upstream's stricter write guard. A trusted gateway
peer does not gain settings-write or restart permission.

The source/config audit retains Kamal secret forwarding and persistent state,
external memory configuration, the single amd64 `runtime-self-hosted` image,
and the downstream Homebrew dispatch. Upstream user-scoped memory fixes,
credential redaction, origin checks and upstream destination checks are retained.
This is source evidence, not deployed-service acceptance.

The first native-backed focused check passed 287 tests across loopback gating,
dashboard authentication, quota registry, Codex rate limits, subscription tracking
and read lifecycle, using the existing Python 3.12 environment and existing native
extension. The extension predates this merge; this check does not qualify the
changed Rust tag protector. Hosted CI and image publication are separate gates.

## Reporting design

The selected approach is a read-only compatibility layer in Headroom, leaving
T3's existing hub connector unchanged. A native T3 adapter was considered but
would add a downstream T3 patch; full CLIProxyAPI management is outside scope.

The adapter exposes stable provider-tracker records, not credential files or
invented account identities. It translates cached Claude/Codex quota snapshots
into T3's expected provider response schemas. It never forwards a requested URL,
headers, or mutations. Missing or expired data is unavailable, not zero usage.
The existing operator-read authentication gate protects both management routes;
the remaining management namespace is refused locally.

After publishing and redeploying, use the Headroom base URL in T3's hub form and
the existing proxy token as its management key. No T3 build update is required.
Providers without a T3 hub reader are not relabeled as another provider.
