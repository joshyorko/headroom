# Self-hosted reconciliation and subscription Limits investigation

## Source boundary

- Starting self-hosted and refreshed origin/self-hosted: `e634a371442ec2f7b7c39e87ec7132d1c583013b`.
- Refreshed upstream/main: `3c66c91eea3ad8cf77d7d66abe484cee876271eb`.
- Initial local merge candidate: `e9794790113c492a391c3434aef6b1a4cb7b7af0`.
- Publication and deployment are separate acceptance gates. The primary checkout remains on self-hosted; all integration work is in this thread's worktree.

The preservation baseline is the **current** self-hosted tree, including the downstream history that explains its behavior. `git diff 17d38e56 e634a371` inventories the fork against its previous upstream baseline. All 263 added/modified paths are listed in `upstream-reconciliation-2026-11-11-files.tsv`; none is missing. A changed path requires behavioral review, not acceptance merely because Git merged it automatically. Historical functionality already absent at e634a371 is not silently reintroduced or counted as preserved working functionality.

## Deployment, packaging and operational checklist

| Capability | Candidate preservation evidence | Remaining qualification |
| --- | --- | --- |
| Kamal controller, executable resolution, dotenv token interpolation, external Qdrant/Neo4j, persistent storage, long timeouts, telemetry-off configuration | `bin/kamal`, `.kamal/secrets`, `.env.kamal.local.example`, `config/deploy.yml` unchanged from starting tree; Kamal configuration/token/wrapper tests | Actual deployment and external backend traffic |
| Local Compose stack and storage | `compose.override.yml` and `scripts/headroom-local` unchanged; persistence and healthcheck tests | Live Compose launch |
| Single amd64 self-hosted GHCR image and Homebrew dispatch | Individual Docker workflow conflict retains `runtime-self-hosted`, amd64 digest download, self-hosted/dev/latest/SHA tagging and tap dispatch | Exact-head hosted CI, image publication and tap acceptance |
| Proxy, code, memory-stack and Bedrock image support | Self-hosted bake target retains all four extras; adds upstream Redis client requirement rather than dropping a fork extra | Built image smoke |
| Dagger wheel/build/install and MCP helpers | `.dagger/`, `dagger.json`, `scripts/headroom-dagger-mcp*`, `scripts/headroom-rebuild-install` unchanged | Clean wheel/native qualification |
| Linuxbrew/compiler and self-hosted version support | `crates/headroom-py/build.rs` compiler library search retained; `_version.py` local-version handling and `release_version.py` local-suffix normalization retained | Installed new package |
| Fork CI and publication governance | Kamal matrix and first-parent commitlint retained; previously deleted release-please/security/governance bots remain deleted; upstream action pins integrated | Exact-head hosted CI |
| Runtime readiness and deployment metadata | `/readyz`, health, deployment version fields retained; source contract tests selected | Native startup-backed tests and deployed readiness |

The primary checkout's unrelated `.serena/project.yml`, `config/deploy.yml`, and untracked feasibility directory are outside this candidate and must remain untouched. No global routing/auth changes or live service restarts are part of this reconciliation.

Detailed behavior reviews are in [provider/wrapper preservation](upstream-reconciliation-2026-11-11-provider.md), [runtime preservation](upstream-reconciliation-2026-11-11-fork-runtime.md), and [fork deletion review](upstream-reconciliation-2026-11-11-fork-runtime-deletions-review.md). All 42 fork-only deleted paths remain absent; [the deletion inventory](upstream-reconciliation-2026-11-11-deletions.tsv) complements the added/modified inventory. These source audits do not replace native startup, dependency-matrix, or live-service acceptance.

## Unresolved preservation gate: Python 3.10

Upstream `3c6f82b06091206379106f8fe1a54f2400ed7a93` raises `requires-python` from `>=3.10` to `>=3.11`, removes the `tomli` backport, and makes the patched `filelock>=4.2.1` floor unconditional. The starting fork advertised Python 3.10 support. Adopting the new minimum would remove that packaging capability; merely reverting the metadata would falsely advertise compatibility and conflict with dependencies requiring 3.11. This remains **unresolved**. The local candidate must not be published or called preservation-accepted until an explicit support decision or independently verified compatibility backport resolves it. A Python 3.11 wheel build cannot close this gate.

The packaging audit also caught upstream `a8905214d949cdc42b1d76fbc83146f51e0c4f19` removing ML, memory, evals and voice from `[all]`. Those four baseline extras are restored in this fork; the separate lean profile remains torch-free. `test_self_hosted_all_profile_keeps_ml_memory_evals_and_voice` records this contract. Updated MCP SDK 2 dependency/runtime interoperability remains a separate dependency qualification gate; tests using the old prepared environment cannot prove it.

## Conflict decisions requiring explicit preservation

- Codex root-provider rewriting combines upstream TOML 1.1 parsing with fork remote/realtime routes and raw-input registrar parsing.
- OpenRouter/Hermes routing and credential scrubbing remain alongside upstream route advice and admission handling.
- Traffic learning combines upstream retry/idempotency with fork per-user/backend isolation; project-scoped requests remain fail-closed.
- Memory tools retain both request-context-aware and legacy handler signatures.
- Canonical MemoryHandler receives its actual request context. A legacy adapter can run scoped traffic only when its resolver selects the same backend and provides the effective composite user identity; otherwise dispatch explicitly returns `legacy_request_scope_unsupported`. No canonical legacy-signature implementation was found in the sampled history. The compatibility adapter is therefore tested as an adapter contract, not claimed to be a historical production implementation. This fail-closed limitation is explicit and requires review; silently dropping project scope is not accepted.
- Code-memory defaults remain Serena, as on self-hosted, while explicit opt-out continues to work. Upstream's switch to an opt-in default is not adopted.
- Rust auth classification retains previously accepted OAuth tokens and adds upstream's case-insensitive scheme/real token format fixes; the `lru` dependency retains upstream's soundness update.
- Release workflow tests retain fork publication contracts; assertions requiring already-retired upstream release bots are not reintroduced.

## Limits: first changed boundary

T3 commit [`c9dfc404ccde9a4c8be901b287026dd19e4ed19a`](https://github.com/pingdotgg/t3code/commit/c9dfc404ccde9a4c8be901b287026dd19e4ed19a), merged in [PR #18622](https://github.com/pingdotgg/t3code/pull/18622) at **2026-11-11 10:09:26 UTC**, introduces the routing gate. Its parent is `25f4c9d44e98ca3a4b0e51cfecc1db122cc4d87b`.

Before that change, `CodexProvider.ts` requests `account/rateLimits/read` unless `skipNativeUsage` is set. Afterward it first computes `nativeUsage` from account authentication and effective routing; only native HTTPS OpenAI/ChatGPT URLs can call or publish quota. A Headroom HTTP proxy route is therefore unsupported even when that proxy forwards subscription traffic. This is an intentional upstream attribution policy, with a regression for the previously visible account-quota display in this setup.

Evidence distinguishing yesterday's behavior from today's code:

- Pre-update desktop trace records build `main.20261111003011.3a8c250cb0c8` at 2026-11-11 13:37:54 UTC. That build was made at 00:30 UTC (November 10 evening in New York); its source lacks the gate. This is evidence of the pre-update revision, not a captured screenshot from yesterday.
- November 10 tap history also packages `main.20261110184319.5f2bb934d8f2`.
- Installed current CLI/Desktop: `main.20261111173503.7e565c510d6d`, installed November 11 at 13:52:46 New York time. GitHub comparison confirms it includes c9dfc404. The installed bundled implementation contains `routesToNativeOpenai` and the conditional quota RPC.
- Current Codex cache is authenticated/ready, version `0.167.1`, with no windows and `unavailable.reason=unsupported`.
- Current configuration and July/August/October backups select the same Headroom proxy host/path and `requires_openai_auth=true`. Configuration mtime alone cannot date routing changes because unrelated writers update the file.
- A bounded read-only quota probe supplied at handoff succeeded under this effective route. Quota endpoint availability and T3 choosing not to call it are different boundaries.
- A small harness extracted the exact new routing predicate with a valid decoded configuration fixture: Headroom gives `nativeUsage=false`/RPC skipped; a native default route gives true/RPC called. This is branch-level proof, not full T3/UI acceptance.
- Codex 0.167.1's release directory dates to November 11 00:06 New York time, while 0.167.0 is also retained. Directory times do not prove the exact CLI used yesterday; this does not negate the independently demonstrated T3 gate.

## Runtime baseline (not updated by this source merge)

- Local installed/running Headroom commands: Homebrew `selfhosted.e634a371442e`, installed November 3, using its own Python 3.13 environment.
- LAN proxy container: image tag `0b2c91469fb67320692ba5f769046e338319c192_uncommitted_35036859da18908f`; container created October 27. Actual image ID `sha256:06b5a85d441ec494d04cd77aafb9c7107c56b489e9b5ae7fa85c045fed4c54c0`; no OCI revision label. The uncommitted suffix prevents asserting exact source equality from its tag.
- Read-only `/health` and `/readyz` requests returned HTTP 200, healthy, version 0.42.0. These are readiness evidence, not end-to-end provider or Limits acceptance.

## Supported correction boundary

No Headroom URL rewrite, auth change, bypass, rebuild or restart can make T3's exact-host predicate recognize an honest proxy URL. T3 needs to expose authenticated-account quota separately from routing attribution, or offer an explicit trusted subscription-forwarder capability with account identity checks. Keep arbitrary custom providers from being attributed unrelated quota. Any such T3 change needs focused native/API-key/custom-provider/passthrough tests plus installed UI verification. No T3 source modification or publication is included here.

Related T3 reports were searched before reporting. Evidence was added to [existing issue #23054](https://github.com/pingdotgg/t3code/issues/23054#issuecomment-6805363581), following T3's contribution guidance and identifying the model/harness. The existing comment was corrected to link [Headroom upstream](https://github.com/headroomlabs-ai/headroom), not characterize the fork as the cause. [Upstream Codex initialization at 3c66c91](https://github.com/headroomlabs-ai/headroom/blob/3c66c91eea3ad8cf77d7d66abe484cee876271eb/headroom/cli/init.py#L408-L430) selects the custom Headroom provider, HTTP loopback base URL, and ChatGPT authentication requirement. The fork adds remote URLs/realtime settings, but neither is necessary to trigger T3's exact-host rejection. The extracted predicate rejects both upstream's loopback URL and the configured remote URL. This is source/predicate comparison, **not an unmodified-upstream runtime test**. No fork-only quota endpoint/suppression change was identified. No issue or PR was created; no PR implementation was proposed as accepted maintainer scope.

## Validation status

Focused Python provider, wrapping, installation, learning, routing, memory, deployment and packaging tests were run with the existing repository Python 3.12 environment and this worktree on PYTHONPATH. Initial native-startup failures identify missing `headroom._core` in the worktree, not successful preservation proof. Native wheel qualification and the final consolidated affected-suite results are recorded below when complete. No UI fix, deployment, installed package update, or live provider acceptance is implied by source tests.

### Final native qualification

One `dagger call build-wheel export --path <task-scratch>/wheels` build completed using the repository module, Python 3.11 and Rust 1.95.0. Wheel: `headroom_ai-0.44.0-cp310-abi3-manylinux_2_34_x86_64.whl`, 18,401,975 bytes, SHA256 `80dbe48bcf1e5ab3f5fc186cd53b1151d68ea908669ae23191fc24fea797a3fd`. The cp310 ABI tag describes extension ABI compatibility, **not** support for installing the Python package on 3.10.

The built extension was extracted to task scratch and appended to the source package's `__path__` before invoking `pytest.main`; the actual `headroom._core.hello()` returned `headroom-core`. Python dependencies came from the existing repository Python 3.12 environment. No host package/environment was installed or changed. The wheel snapshot preceded final packaging/profile and Python-only preservation edits; this qualifies its unchanged Rust component, not the final installed package/dependency matrix.

The first native-backed run passed **261 tests** across `test_agent_savings`, `test_dashboard_browser_auth`, `test_provider_openai_realtime`, `test_provider_proxy_routes`, `test_proxy_health`, `test_proxy_healthchecks`, `test_proxy_project_savings`, `test_stateless_no_disk`, `test_stats_output_reduction_gate`, `test_responses_memory_dispatch_isolation` and `test_openai_codex_routing`. These execute TestClient startup/request paths and real SQLite isolation checks; this is more than an import smoke. They supersede the earlier missing-core failures in those files, but do not prove live provider/Qdrant/Neo4j or rendered UI behavior.

Other focused receipts: 364 Codex/provider/init/install tests passed; the broader provider/learning batch passed 798 with four native-dependent failures subsequently covered above; runtime source batches passed 446 and 146 with native-dependent failures tracked separately; 76 deployment/workflow tests passed with four skips; an expanded deployment/release batch passed 112 with one action-pin failure, then the affected four CI tests passed after pinning the retained Kamal job's checkout/Python/Ruby actions. Ten packaging/security/dependency-contract tests passed. Counts describe separate, overlapping runs and must not be summed as unique tests.

The restored Serena defaults failed two baseline expectations before restoration and passed afterward. The `[all]` metadata before restoration lacked all four baseline optional features; restored metadata contains them. Actual MemoryHandler/router/SQLite tests pass for canonical and explicitly representative legacy-adapter cases, and a process-only negative mutation of the prior raw-user fallback fails the isolation assertion. No tests were removed to bypass native coverage.

Remaining gates: Python 3.10 compatibility decision/backport; final wheel/dependency install using MCP SDK 2 and the restored `[all]` profile; plugin Node suites; full Rust test matrix; hosted exact-head CI; installed/runtime/deployment and UI acceptance. No push, remote self-hosted update, PR, deployment, restart or global routing/auth change was performed. Temporary build exports and diagnostics are removed at handoff; the source checklists and regression tests remain in this worktree.
