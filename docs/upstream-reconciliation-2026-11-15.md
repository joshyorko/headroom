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

## Reporting validation

- The new tests first reproduced the missing management route, then passed.
- Final hub/auth/loopback batch: 213 passed, including 32 new reporting tests.
- Final hub/prefix-cache batch after a type-only variable rename: 144 passed.
- Broader upstream/fork batch: 575 passed and four skipped initially; three
  failures were missing newly required development packages. After installing
  the declared `cryptography` and SOCKS dependencies in the existing project
  environment, all five selected TLS/proxy cases passed. No production code
  change was needed for those failures.
- Ruff and targeted mypy passed. Two upstream typing incompatibilities were
  corrected without changing runtime behavior: annotate the HTTPX raw host
  as bytes, and avoid reusing a tuple variable for its mutable intermediate.
- A Luna contract check executed the installed T3 bundle's actual account,
  Claude usage, Codex usage and response-envelope decoders against synthetic
  responses from the new HTTP routes. All accepted the responses. This did
  not execute T3's full provider effect or render the T3 UI.
- Independent Luna reviews found no actionable issue in the reviewed merge
  controls and reporting adapter/routes.

These checks use the existing native extension; hosted image publication must
build and smoke-test the new native code before redeployment. Live provider
polling and T3 UI acceptance remain post-deployment gates.
