# Selective Upstream Reconciliation Design

## Goal

Bring selected changes from `headroomlabs-ai/headroom` `main` into Josh's
`self-hosted` branch without losing downstream behavior, then publish the
verified branch and automatically trigger the existing Homebrew acceptance
pipeline.

## Baseline and Scope

- Downstream baseline: `self-hosted` at `ad7eea0d`.
- Upstream inventory baseline: `upstream/main` at `6d2254df`.
- Divergence at design time: 44 downstream-only and 54 upstream-only commits.
- No merge commit from `upstream/main` is allowed.
- Each accepted unit is one upstream commit or the smallest dependency-complete
  group of upstream commits.
- Upstream release automation, governance, documentation, and dependency-only
  changes are excluded unless an accepted runtime change requires them.

## Behavior Preservation Contract

Every accepted group must preserve these downstream capabilities:

- self-hosted Docker, Compose, Dagger, GHCR, Kamal, and trusted-LAN settings;
- OpenRouter routing and authentication stripping;
- DeepSeek aliases and pricing behavior;
- external Qdrant and Neo4j memory backends and project-scoped memory;
- RTK project and lifetime savings ingestion, persistence, and dashboard output;
- Codex installation, wrapping, MCP project scope, and Serena integration;
- stateless operation and configured data paths;
- realtime voice passthrough;
- durable Copilot proxy authentication and refresh behavior;
- semantic-cache shaping fields and cache-key policy;
- downstream release metadata and intentionally removed upstream automation.

An upstream implementation may replace downstream code only when tests prove
that it satisfies the same observable contract.

## Upstream Change Groups

### 1. Security and isolated crash fixes

Includes loopback write CSRF protection, malformed memory `entity_refs`
sanitization, CCR marker hash verification, and closely related correctness
fixes. These are the first candidates because they are narrow and high value.

### 2. CCR and provider protocol correctness

Includes retrieval-tool history repair, stateless Responses lifecycle fixes,
buffered SSE handling, Anthropic stream behavior, tool-search resolution,
Gemini continuation accounting, OpenAI usage propagation, WebSocket model
attribution, signed-thinking accounting, and response-cache replay framing.
These changes must be ordered by their upstream dependencies and tested across
OpenAI, Anthropic, Gemini, Codex WebSocket, and downstream realtime paths.

### 3. Installation and wrapper safety

Includes Serena launch latency, Codex config mutation preflight, deployment
profile resolution, Claude/Copilot/xAI routing, and platform installer fixes.
Linux and Codex-relevant fixes are preferred; unrelated Windows and macOS
changes remain excluded unless shared code makes them inseparable.

### 4. Savings attribution and extension telemetry

Includes unified savings attribution and extension-provided latency/cost data.
This group has the highest downstream collision risk because the fork adds RTK
project and lifetime metrics. It requires explicit equivalence tests before any
implementation is retained.

### 5. Runtime rollout controls

The deterministic rollout feature is a large, independent addition. It is
considered only after the existing proxy and metrics groups are stable and is
accepted only if it does not change default behavior.

### 6. Docker, release, dependency, and governance maintenance

Bedrock image support and loopback-only Compose binding are evaluated against
the self-hosted deployment contract. Generic upstream publishing, release
governance, and dependency bumps are not imported by default. Required
dependency changes are minimized to the accepted runtime group's needs.

## Integration Method

1. Work only on `patchraptor/headroom-selective-upstream-20260817` in an
   isolated worktree.
2. Inspect each candidate's full patch, parent assumptions, tests, and overlap
   with downstream-only files.
3. Add or identify a failing regression test for the behavior being imported.
4. Apply the upstream commit without committing, then adapt only the collision
   points necessary to preserve downstream behavior.
5. Run the candidate's focused upstream tests and the affected downstream
   acceptance tests.
6. Commit the accepted unit locally with upstream commit and PR references.
7. Stop and discard the unit if its dependency boundary is unclear or a
   downstream contract cannot be demonstrated.
8. After all retained groups, run the complete merge-sensitive Python, Rust,
   Dagger, packaging, Docker configuration, and workflow validation gates.

The branch history remains reviewable: one local commit per accepted upstream
commit or coherent dependency group. No acceptance group is hidden inside a
single bulk reconciliation commit.

## Verification Gates

Each group receives:

- upstream tests added or changed by that group;
- focused downstream tests for every overlapping subsystem;
- Ruff and formatting checks for touched Python files;
- Rust formatting and focused crate tests for touched Rust code;
- lockfile validation when dependency metadata changes;
- a clean diff and explicit review of deleted behavior.

Final verification additionally includes the established overlap suites,
content-router and provider tests, settings and forwarded-header tests,
self-hosted deployment tests, Dagger wheel smoke, and an offline Homebrew
installation smoke. Known order-dependent full-suite failures must be rerun in
isolation and reported separately; they cannot be silently treated as success.

## Publication and Downstream Build

After local verification:

1. Push the reviewed reconciliation branch or the verified `self-hosted`
   result according to the final branch state.
2. Ensure required Headroom checks complete successfully.
3. Update `self-hosted` only with the reviewed linear commit stack.
4. Let the Headroom Docker workflow build and publish the self-hosted image.
5. On a successful Docker workflow run caused by a push to `self-hosted`, use
   `HOMEBREW_TOOLS_PAT` to dispatch `joshyorko/homebrew-tools` workflow
   `tap-auto-update.yml` on `main` with `slot_id: headroom-daily`.
6. Verify the dispatch was received, `headroom-self-hosted` was selected, its
   source SHA matches the pushed Headroom commit, the bundle was published,
   the formula was updated, and the offline Linuxbrew smoke passed.

This reuses the existing RCC cross-repository `workflow_dispatch` contract.
The Homebrew repository already tracks the `self-hosted` Git head and therefore
needs no receiver change unless live verification exposes a contract mismatch.

## Failure Handling

- A candidate that fails its focused gate is removed before the next group.
- A candidate that passes upstream tests but breaks a downstream behavior is
  adapted in the same group or rejected.
- A failed push check blocks promotion to `self-hosted`.
- A failed Docker run blocks the Homebrew dispatch.
- A failed Homebrew build leaves the Headroom push intact but is reported as a
  downstream packaging failure; it is fixed in the owning repository without
  rewriting verified Headroom history.

## Completion Criteria

- Every retained upstream change has a stated reason, upstream reference, and
  independently verified local commit.
- All behavior-preservation gates pass or have an explicitly documented,
  reproducible infrastructure exception.
- `origin/self-hosted` contains the reviewed linear stack.
- The corresponding Headroom Docker workflow succeeds.
- The matching Homebrew workflow succeeds and publishes a formula whose source
  provenance points to the final `self-hosted` commit.
