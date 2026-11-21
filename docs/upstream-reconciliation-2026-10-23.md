# Upstream reconciliation, 2026-10-23

Baseline: `self-hosted` / `cb528b99`.
Upstream: `main` / `e995eb9f1dacac7ed548758406de6c1508caef95`, including release 0.41.0.
Scope: 386 upstream commits since the previous common ancestor. Candidate branch:
`codex/self-hosted-upstream-20261023`, targeting `self-hosted` through a draft PR.
No production deployment is part of this update.

## Reconciliation decisions

| Group | Decision | Contracts |
| --- | --- | --- |
| Cache and accounting | Accept upstream fixes | Keep read/write/uncached buckets disjoint, count inferred writes once, and separate provider discounts from Headroom savings. Preserve downstream project and lifetime attribution. |
| Dashboard | Adapt | Accept upstream canonical dollar cards in place of the duplicate proxy-dollar card. Retain downstream output-estimate reliability and project/lifetime fields. |
| Provider routing | Adapt | Keep downstream Copilot, OpenRouter, project/client paths, and Codex realtime support while accepting advertised Copilot hosts and next-edit routing. |
| Request boundaries | Accept upstream guards | Keep cache partitions, proxy-token scrubbing, authenticated WebSockets, body limits, and verified workspace registration. Preserve explicit trusted-dashboard CIDRs. |
| Memory | Adapt | Retain Qdrant/Neo4j and request-scoped identity. Persist default-scope pending learning without persisting request-specific backend/user evidence. |
| Learning | Adapt | Retain Codex progress, handwritten instructions, override discovery, 32 KiB active and 16 KiB generated limits, and full archive before active writes. Accept upstream injection sanitization and digest budgets. |
| Model loading and compression | Accept upstream fixes | Restore pinned HF revisions and offline guards. Keep existing deployment compression settings; do not tune for a higher percentage. |
| OpenCode | Adapt | Restore the default-only entry required by current upstream packaging and retain remote session-token transport. |
| Packaging | Accept upstream manifests and locks | Keep the single amd64 `runtime-self-hosted` image with `proxy,code,memory-stack,bedrock`, plus Homebrew dispatch. |
| Kamal and Compose | Preserve and adapt | Retain accessories, persistent state, `/readyz`, 600-second timeouts, and trusted routing. Explicitly default anonymous telemetry off. |
| Upstream governance | Preserve fork exclusions | Keep Dependabot, release-please manifest, PR-health, and upstream security workflow deletions. Exclude the new weekly issue writer assigned to an upstream maintainer. Keep runtime validation workflows. |

## Compatibility and operational changes

- Non-loopback listeners now refuse startup without a proxy token or explicit
  `HEADROOM_ALLOW_UNAUTHENTICATED_BIND=1`. The existing Kamal LAN listener needs
  a token and compatible clients before deployment. Kamal forwards a configured
  token as a secret; no token was generated and no bypass is enabled here.
- Base Compose now requires `HEADROOM_PROXY_TOKEN`. Configure it before using
  that deployment path. Health probes remain exempt from token authentication.
- Extension middleware runs inside authentication and body limits. An extension
  cannot replace proxy-token authentication.
- Upstream suppresses shared live traffic learning for project-scoped Codex
  Responses until the learner's full history is isolated. This update retains
  that guard. Local transcript learning through `headroom learn` is unchanged.
- The `[crewai]` package extra was removed. The integration remains available;
  install CrewAI separately if you use it.
- Copilot Business/Enterprise routing uses GitHub's advertised host by default.
  Explicit host settings still win. `GITHUB_COPILOT_USE_ADVERTISED_HOST=0`
  restores public-host routing.
- Anonymous beacon uploads were already default-on before this update. The new
  `HEADROOM_TELEMETRY=off` behavior also disables uploads unless beacon-on is
  explicitly requested. This fork sets `HEADROOM_BEACON=off`,
  `HEADROOM_TELEMETRY=off`, and `DO_NOT_TRACK=1` in deployment defaults.
- Prefix-state restart persistence is opt-in through `HEADROOM_PREFIX_STATE_FILE`,
  supports graceful shutdown with one worker, and stores conversation content.
  This update does not enable it or claim warm restarts.
- Savings fixes can change displayed dollars without changing traffic. Provider
  cache discounts remain separate from direct Headroom savings. A shaped-response
  count is an application count, not a measured token-saving count.
- Dependency floors advance, including MCP `>=1.30.0`, hf-xet `>=1.6.0`, and the
  updated security constraints. Use the candidate-built native extension.

## Adversarial review

Astra at high reasoning reproduced two introduced regressions: duplicate or
out-of-scope Responses learning, and valid realtime clients rejected after token
scrubbing. Both have runtime regressions and were closed in independent review.
Further review narrowed the Codex MCP insertion repair to preserve closed owner
blocks and literal markers inside instructions. Duplicate cleanup now checks
parsed ownership and preserves indented foreign tables and following MCP blocks.
All introduced P1 findings are closed in the final independent source review.

The initial review also records inherited limits: non-Codex shared tool recovery
history is not fully scoped, and the dashboard can describe steering as applied
when its payload is available but inactive. Complete provider-marker examples
inside multiline instructions can also be stripped by inherited cleanup logic;
the reviewer reproduced that behavior on the original baseline. These remain
separate limitations, not acceptance claims.
OpenCode's legacy production dependency chain
`@opencode-ai/plugin -> effect -> toml` retains three high npm audit findings.
They were present before this update; dependency audit remediation is separate.
An inherited LiteLLM cold import can fetch its pricing map despite Headroom's
offline switch. `LITELLM_LOCAL_MODEL_COST_MAP=true` prevents that fetch; this is
separate from the anonymous beacon and is not enabled in the deployment here.

## Validation

- Dagger native wheel/import/CLI smoke passed for 0.41.0. Rust 1.95.0 formatting,
  Clippy with warnings denied, and 1,656 workspace tests passed; 3 were ignored.
- OpenCode's 57 tests and typecheck passed. Repository Ruff checks and formatting
  passed, as did the configured commit hooks, including isolated mypy.
- The first broad offline Python run recorded 16,822 passed, 31 failed, 583 skipped,
  and 15 deselected. All 31 failed cases passed together after repairs. Fresh
  final-source coverage passed 2,371 tests with 11 skipped. The complete suite
  was not rerun after the final ownership repair; hosted CI remains a gate.
  No live provider tests are included.
- The 31 failures cover Codex ownership/duplicate cleanup, stale progress test
  doubles, CLI test-state leakage, hook metadata, an omitted SOCKS test dependency,
  and an embedding cache hidden by isolated HOME. The cached model is reused in
  an isolated copy without downloading or modifying the original cache.
- Mypy with the optional memory stack installed reports 8 Qdrant argument-type
  errors. The previous baseline reproduces the same 8 errors in that environment.
- Kamal rendering with and without a synthetic token verifies telemetry-off
  defaults and the active bind guard. Live telemetry, production traffic, external
  memory, image publication, and deployment require their own operational gates.

## Reproduce the inventory

Run in this repository:

```sh
rtk git log --oneline cb528b99..e995eb9f1dacac7ed548758406de6c1508caef95
rtk git diff cb528b99...e995eb9f1dacac7ed548758406de6c1508caef95 --stat
```
