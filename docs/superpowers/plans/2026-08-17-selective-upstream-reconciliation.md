# Selective Upstream Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate selected upstream Headroom runtime fixes into the self-hosted fork without regressing downstream behavior, then push the verified stack and trigger its Homebrew build.

**Architecture:** Apply upstream changes as dependency-aware, reviewable groups rather than merging `upstream/main`. For each behavior, install the upstream tests first and observe the expected failure, apply the production patch, adapt only downstream collision points, and commit after focused upstream and downstream gates pass. Publish by fast-forwarding `origin/self-hosted`; the successful self-hosted Docker workflow dispatches the existing `headroom-daily` Homebrew slot.

**Tech Stack:** Python 3.11-3.13, pytest, Ruff, Rust/Cargo, Dagger, Docker Buildx, GitHub Actions, Homebrew/Linuxbrew.

## Global Constraints

- Work only in `/var/home/kdlocpanda/.codex/worktrees/headroom-selective-upstream-20260817` on `patchraptor/headroom-selective-upstream-20260817`.
- Do not merge `upstream/main` and do not use wholesale ours/theirs conflict resolution.
- Preserve every capability in `docs/superpowers/specs/2026-08-17-selective-upstream-reconciliation-design.md`.
- Use `rtk` for every shell command.
- Apply tests before production code and observe the expected failure for every imported behavior.
- Keep one local commit per accepted upstream commit or smallest dependency-complete group, with `Upstream-Commit:` trailers.
- Do not import release automation, governance, platform-only changes, or dependency churn unless a retained runtime change requires them.
- Never force-push. Before publishing, fetch `origin/self-hosted` and require it to remain an ancestor of the candidate.
- Do not deploy the Kamal application; publication scope is Git, GitHub Actions, GHCR workflow execution, and Homebrew build verification.

---

### Task 1: Establish the clean baseline and reconciliation ledger

**Files:**
- Create: `docs/upstream-reconciliation-2026-08-17.md`
- Test: existing merge-sensitive tests listed below

**Interfaces:**
- Consumes: approved design and upstream range `self-hosted..upstream/main`.
- Produces: a complete ledger assigning every upstream-only commit to accepted, adapted, superseded, or excluded.

- [ ] **Step 1: Verify isolation and refs**

Run:

```bash
rtk git status --short --branch
rtk git fetch upstream main
rtk git fetch origin self-hosted
rtk git rev-list --left-right --count self-hosted...upstream/main
```

Expected: clean feature branch; `origin/self-hosted` equals the feature branch's base; upstream remains 54 commits ahead of the merge base.

- [ ] **Step 2: Run the downstream preservation baseline**

Run:

```bash
UV_CACHE_DIR=/tmp/headroom-upstream-uv-cache rtk test uv run --extra dev python -m pytest -q tests/test_self_hosted_deploy_config.py tests/test_proxy_project_savings.py tests/test_dashboard_agent_usage.py tests/test_dashboard_token_savings.py tests/test_proxy_settings_endpoints.py tests/test_proxy_loopback_gating.py tests/test_provider_proxy_routes.py tests/test_provider_openai_realtime.py tests/test_proxy_copilot_auth_hooks.py tests/test_memory_handler_native_ops.py tests/test_semantic_cache_key_policy.py tests/test_cli/test_wrap_codex.py
```

Expected: all selected baseline tests pass before upstream code is applied.

- [ ] **Step 3: Write the commit ledger**

Record all 54 upstream-only commits. Mark `942af56f` and `1b0b0b89` superseded because they are empty replay commits. Exclude `93f2d7a2`, `e269afb9`, `7e312805`, `aa811fa9`, `ac8646aa`, and `cbb950a4` as upstream release/governance automation; exclude `ddd2a259`, `ddd9f767`, `6d87825f`, and `96c25f51` as unrelated Windows/macOS-only behavior; exclude dependency-only commits until a retained group proves a requirement. Give every retained or excluded commit a one-sentence reason.

- [ ] **Step 4: Validate and commit the ledger**

Run:

```bash
rtk git diff --check
rtk git add docs/upstream-reconciliation-2026-08-17.md
rtk git commit -m "docs: inventory selective upstream reconciliation"
```

Expected: one documentation-only commit and a clean worktree.

---

### Task 2: Import memory sanitation and CCR marker validation

**Files:**
- Modify: `headroom/memory/models.py`
- Modify: `headroom/memory/backends/local.py`
- Modify: `headroom/memory/adapters/hnsw.py`
- Modify: `headroom/memory/adapters/sqlite.py`
- Modify: `headroom/memory/adapters/sqlite_vector.py`
- Modify: `headroom/ccr/tool_injection.py`
- Modify: `headroom/proxy/handlers/openai.py`
- Test: `tests/test_memory/test_entity_ref_sanitization.py`
- Test: `tests/test_ccr_tool_injection.py`
- Test: `tests/test_proxy/test_anthropic_ccr_deferred_injection.py`

**Interfaces:**
- Consumes: downstream memory adapters and compressed-marker validation.
- Produces: normalized string entity references and hash-verified marker advertisement.

- [ ] **Step 1: Apply only tests from `2d1e96b8` and `41dab2d0`**

Use each upstream commit's test diff while leaving production files unchanged.

- [ ] **Step 2: Verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/headroom-upstream-uv-cache rtk test uv run --extra dev python -m pytest -q tests/test_memory/test_entity_ref_sanitization.py tests/test_ccr_tool_injection.py tests/test_proxy/test_anthropic_ccr_deferred_injection.py
```

Expected: failures showing dict-shaped entity references are not normalized and mismatched marker hashes remain advertisable.

- [ ] **Step 3: Apply production changes and preserve external memory behavior**

Apply non-test diffs from `2d1e96b8` and `41dab2d0`. Resolve `headroom/memory/backends/local.py` by retaining external Qdrant/Neo4j selection and project context while adding entity-reference sanitation. Resolve CCR files by retaining downstream tool logging and project-scoped retrieval while enforcing hash equality.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
UV_CACHE_DIR=/tmp/headroom-upstream-uv-cache rtk test uv run --extra dev python -m pytest -q tests/test_memory/test_entity_ref_sanitization.py tests/test_memory_handler_native_ops.py tests/test_ccr_tool_injection.py tests/test_proxy/test_anthropic_ccr_deferred_injection.py tests/test_proxy_anthropic_cache_stability.py
rtk git diff --check
rtk git add -A && rtk git commit -m "fix: sanitize memory refs and validate CCR markers" -m "Upstream-Commit: 2d1e96b85c61cc7aab821750f549f24d54cbb6f5" -m "Upstream-Commit: 41dab2d09925658b96fed492d534346ce1930f4c"
```

Expected: focused memory and CCR suites pass.

---

### Task 3: Import retrieval history repair and core-tool residency

**Files:**
- Modify: `headroom/proxy/handlers/anthropic.py`
- Modify: `headroom/proxy/handlers/openai.py`
- Modify: `headroom/proxy/helpers.py`
- Modify: `headroom/proxy/tool_injection_logging.py`
- Test: `tests/test_ccr_tool_always_on.py`
- Test: `tests/test_ccr_retrieve_history_repair.py`
- Test: `tests/test_proxy/test_anthropic_streaming_ccr_retrieve.py`

**Interfaces:**
- Consumes: downstream project-scoped `headroom_retrieve` and tool injection logging.
- Produces: sessionless history repair, Anthropic-compatible repair, and resident prefixed core tools.

- [ ] **Step 1: Apply tests from `d6d121e3`, `7de35739`, and `2f4d001c`**

- [ ] **Step 2: Verify RED**

Run the three listed test modules and confirm missing history repair or tool residency failures.

- [ ] **Step 3: Apply the production diffs**

Preserve downstream project routing and telemetry in `helpers.py`; use upstream's history scanning and provider-specific tool-array repair. Do not apply empty replay `942af56f`.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
UV_CACHE_DIR=/tmp/headroom-upstream-uv-cache rtk test uv run --extra dev python -m pytest -q tests/test_ccr_tool_always_on.py tests/test_ccr_retrieve_history_repair.py tests/test_proxy/test_anthropic_streaming_ccr_retrieve.py tests/test_plugins_hermes_retrieve.py
rtk git diff --check
rtk git add -A && rtk git commit -m "fix: repair retrieval history and retain core tools" -m "Upstream-Commit: d6d121e399938edffce5258697ad5046c84eade3" -m "Upstream-Commit: 7de35739c61bed385dd078aee1b36865938c486d" -m "Upstream-Commit: 2f4d001c9ffd7f856c8dab3e31a8240a1c676f04"
```

---

### Task 4: Import Responses, streaming, cache, and provider accounting fixes

**Files:**
- Modify: `headroom/proxy/handlers/openai.py`
- Modify: `headroom/proxy/handlers/anthropic.py`
- Modify: `headroom/proxy/handlers/gemini.py`
- Modify: `headroom/proxy/handlers/streaming.py`
- Modify: `headroom/proxy/helpers.py`
- Modify: `headroom/proxy/body_forwarding.py`
- Test: `tests/test_openai_codex_ws_lifecycle.py`
- Test: `tests/test_proxy_response_cache_replay.py`
- Test: `tests/test_ccr_buffered_stream_signed_thinking.py`
- Test: `tests/test_gemini_ccr_continuation_usage.py`
- Test: `tests/test_ws_http_fallback.py`

**Interfaces:**
- Consumes: downstream stateless mode, realtime passthrough, cache-key policy, and provider routing.
- Produces: correct buffered SSE adaptation, CCR lifecycle, cache framing, usage propagation, model attribution, and signed-thinking accounting.

- [ ] **Step 1: Apply tests from the dependency-ordered group**

Apply test diffs from `d76fce04`, `f1c34d33`, `8a1d38bc`, `8ea87e78`, `9d370592`, `a01897c7`, `a06a51ec`, `536c949a`, and `b3f44363`.

- [ ] **Step 2: Verify RED**

Run the five listed modules plus `tests/test_proxy_byte_faithful_forwarding.py`; require failures in the newly imported cases while existing downstream cases remain runnable.

- [ ] **Step 3: Apply production diffs in upstream order**

Retain downstream OpenRouter auth stripping, realtime endpoint passthrough, semantic-cache key construction, traffic learning, and project savings hooks. Adopt upstream protocol state machines and wire-accounting fixes. Reject any hunk that removes a downstream hook without an equivalent call site.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
UV_CACHE_DIR=/tmp/headroom-upstream-uv-cache rtk test uv run --extra dev python -m pytest -q tests/test_openai_codex_ws_lifecycle.py tests/test_proxy_response_cache_replay.py tests/test_ccr_buffered_stream_signed_thinking.py tests/test_gemini_ccr_continuation_usage.py tests/test_ws_http_fallback.py tests/test_proxy_byte_faithful_forwarding.py tests/test_provider_openai_realtime.py tests/test_openai_traffic_learning.py tests/test_proxy_semantic_cache_key.py tests/test_proxy_project_savings.py
rtk git diff --check
rtk git add -A && rtk git commit -m "fix: reconcile proxy protocol lifecycle" -m "Upstream-Commit: d76fce04a39b3f206e38a02e012d50b2c728f7ca" -m "Upstream-Commit: f1c34d336cf35db341153c1c65e8c15219398340" -m "Upstream-Commit: 8a1d38bc5da87b49a530df22090c3a156d2d0cd6" -m "Upstream-Commit: 8ea87e7804abfbb55beaf869e50dcb66deab975a" -m "Upstream-Commit: 9d370592b022d01e6bc44a88649a611507794776" -m "Upstream-Commit: a01897c791f4bb6471defafd560d29d491eb2df8" -m "Upstream-Commit: a06a51eca63f88271dfa77f2ee6bf3c8da6b24e4" -m "Upstream-Commit: 536c949a692f4855719d71d612abc4968040286b" -m "Upstream-Commit: b3f443636d279d4bad845a8ef2bddb7ca50e9bc6"
```

---

### Task 5: Import provider routing and pricing correctness

**Files:**
- Modify: `headroom/proxy/helpers.py`
- Modify: `headroom/pricing/litellm_pricing.py`
- Modify: `headroom/providers/anthropic.py`
- Modify: `headroom/providers/openai.py`
- Modify: `headroom/providers/cohere.py`
- Modify: `headroom/providers/google.py`
- Modify: `headroom/providers/litellm.py`
- Test: `tests/test_proxy_handler_helpers.py`
- Test: `tests/test_netcost_gate.py`
- Test: `tests/test_providers/test_anthropic.py`

**Interfaces:**
- Consumes: downstream OpenRouter and DeepSeek aliases.
- Produces: correct top-level system-role relocation, one-hour cache-write pricing, and Anthropic 1M-context model pricing.

- [ ] **Step 1: Apply tests from `9fde1275`, `ef7e07e0`, and `6d2254df` and verify RED**

- [ ] **Step 2: Apply production diffs**

Preserve downstream aliases and auth handling. Add upstream system-message normalization and pricing tiers without replacing local model resolution.

- [ ] **Step 3: Verify GREEN and commit**

Run:

```bash
UV_CACHE_DIR=/tmp/headroom-upstream-uv-cache rtk test uv run --extra dev python -m pytest -q tests/test_proxy_handler_helpers.py tests/test_netcost_gate.py tests/test_providers/test_anthropic.py tests/test_pricing_litellm.py tests/test_pricing_from_litellm.py tests/test_provider_proxy_routes.py
rtk git diff --check
rtk git add -A && rtk git commit -m "fix: reconcile provider routing and pricing" -m "Upstream-Commit: 9fde12753416a6102535235b822e44afebf76e9e" -m "Upstream-Commit: ef7e07e0f5d6510ab96b5abb1698b1b681b5f9bf" -m "Upstream-Commit: 6d2254dfb5eb97f92249e0ee7aa04b2697adfa69"
```

---

### Task 6: Import Linux-relevant wrapper, install, and provider fixes

**Files:**
- Modify: `headroom/cli/install.py`
- Modify: `headroom/install/planner.py`
- Modify: `headroom/cli/proxy.py`
- Modify: `headroom/cli/wrap.py`
- Modify: `headroom/cli/doctor.py`
- Modify: `headroom/providers/claude/`
- Modify: `headroom/providers/copilot/`
- Modify: `headroom/providers/grok_build/`
- Test: corresponding `tests/test_cli/` and provider tests

**Interfaces:**
- Consumes: downstream Codex, Serena, Copilot token refresh, and proxy detach behavior.
- Produces: non-blocking Serena launch, preflight-safe Codex mutation, profile-aware install, Claude auth conflict detection, compatible VS Code modes, Copilot CAPI routing, xAI upstream routing, configurable Claude 1M fallback, and accurate doctor output.

- [ ] **Step 1: Apply tests from the wrapper group and verify RED**

Use `6147883d`, `82526191`, `b7f342c1`, `1aa701ad`, `2d88e31a`, `be5b26d8`, `c8310819`, and `2a847252`. Keep downstream Copilot refresh tests active.

- [ ] **Step 2: Apply production diffs in upstream order**

Do not import Windows/macOS-only commits. Resolve `wrap.py` by retaining downstream Codex raw-TOML parsing, proxy detach, and durable Copilot behavior.

- [ ] **Step 3: Verify GREEN and commit**

Run:

```bash
UV_CACHE_DIR=/tmp/headroom-upstream-uv-cache rtk test uv run --extra dev python -m pytest -q tests/test_cli/test_install_cli.py tests/test_install/test_planner.py tests/test_cli/test_wrap_serena_boost.py tests/test_cli/test_wrap_codex.py tests/test_cli/test_wrap_bridge.py tests/test_cli/test_wrap_vscode.py tests/test_cli/test_wrap_vscode_claude.py tests/test_cli_doctor.py tests/test_provider_copilot_vscode_config.py tests/test_proxy_copilot_auth_hooks.py tests/test_cli/test_wrap_copilot.py tests/test_provider_grok_build.py
rtk git diff --check
rtk git add -A && rtk git commit -m "fix: reconcile wrappers and provider setup" -m "Upstream-Commit: 6147883d5e3a92cc7b890e6c05dce4391090c7e4" -m "Upstream-Commit: 82526191a103a8d0e079d170e47631b3c2bcb0d9" -m "Upstream-Commit: b7f342c153a3e6e43a9d3df006bcd4dd69842d00" -m "Upstream-Commit: 1aa701adaa1ff792dd0e701f498d8d0326655670" -m "Upstream-Commit: 2d88e31a404e2be6c1c428deb2a387599eb820ba" -m "Upstream-Commit: be5b26d807be81d83594c9144a8520f6f0f1b273" -m "Upstream-Commit: c8310819a4221b0d120436786fc499a24c8e55f1" -m "Upstream-Commit: 2a8472525d3a027c95dc38a10c4b6707b482cabc"
```

---

### Task 7: Reconcile savings attribution without losing RTK metrics

**Files:**
- Create: `headroom/proxy/savings_attribution.py`
- Modify: `headroom/observability/metrics.py`
- Modify: `headroom/perf/analyzer.py`
- Modify: `headroom/proxy/handlers/anthropic.py`
- Modify: `headroom/proxy/handlers/openai.py`
- Modify: `headroom/proxy/savings_tracker.py`
- Modify: `headroom/proxy/server.py`
- Modify: `headroom/dashboard/templates/dashboard.html`
- Test: `tests/test_observability_metrics.py`
- Test: `tests/test_extension_attribution.py`
- Test: downstream RTK/project/lifetime suites

**Interfaces:**
- Consumes: local RTK project/lifetime ingestion and upstream request-level attribution.
- Produces: one attribution model that keeps local persistence/dashboard fields while accepting provider and extension latency/cost savings.

- [ ] **Step 1: Apply tests from `31452426` and `f9807fd6`; verify RED**

Do not apply empty replay `1b0b0b89`. Confirm upstream attribution tests fail because the new attribution model is absent while downstream RTK tests still pass.

- [ ] **Step 2: Apply production diffs and adapt collision points**

Use upstream attribution as the request-level source of truth. Preserve local `context_tool`/RTK project keys, lifetime aggregation, trusted dashboard exposure, and existing persisted schema. Extension attribution augments rather than replaces local totals.

- [ ] **Step 3: Verify GREEN and commit**

Run:

```bash
UV_CACHE_DIR=/tmp/headroom-upstream-uv-cache rtk test uv run --extra dev python -m pytest -q tests/test_observability_metrics.py tests/test_extension_attribution.py tests/test_turn_hook_usage.py tests/test_turn_hooks.py tests/test_proxy_stats_recent_requests.py tests/test_proxy_project_savings.py tests/test_dashboard_agent_usage.py tests/test_dashboard_token_savings.py tests/test_context_tool_report.py tests/test_cli/test_mcp_report_rtk.py
rtk git diff --check
rtk git add -A && rtk git commit -m "feat: reconcile savings attribution" -m "Upstream-Commit: 314524264512c9bc489ac17d5f45034af4fd7675" -m "Upstream-Commit: f9807fd69e220f43068ec168515ae886dd36166f"
```

---

### Task 8: Import compatible runtime and packaging support

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `headroom/_ort.py`
- Modify: `headroom/binaries.py`
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `docker-bake.hcl`
- Modify: `plugins/openclaw/`
- Test: dependency, Docker, and plugin contract tests

**Interfaces:**
- Consumes: self-hosted Docker/Kamal and Python dependency contract.
- Produces: MCP v1 compatibility, Rust ONNX API-24 compatibility, Bedrock-ready Docker packaging, loopback Compose publication, and resilient OpenClaw proxy behavior.

- [ ] **Step 1: Apply tests from `6077e5a1`, `a3fe5cb6`, `eafdf11a`, `481e0b83`, and `6576ef63`; verify RED**

- [ ] **Step 2: Apply production diffs**

Retain the self-hosted Docker target, GHCR registry, Kamal architecture, external memory environment, and Compose overrides. Regenerate `uv.lock` only through the repo's locked `uv` workflow if direct patch application conflicts.

- [ ] **Step 3: Verify GREEN and commit**

Run:

```bash
UV_CACHE_DIR=/tmp/headroom-upstream-uv-cache rtk test uv run --extra dev python -m pytest -q tests/test_mcp_dependency_contract.py tests/test_onnx_dependency_contract.py tests/test_transforms/test_ort_dylib.py tests/test_docker_compose_persistence.py tests/test_self_hosted_deploy_config.py tests/test_bedrock_region.py tests/test_backends/test_bedrock_botocore_preflight.py tests/test_plugin_manifests.py
rtk test npm --prefix plugins/openclaw test
rtk git diff --check
rtk git add -A && rtk git commit -m "fix: reconcile runtime packaging contracts" -m "Upstream-Commit: 6077e5a149ee6548edaff033f2cdffffce6ea0cf" -m "Upstream-Commit: a3fe5cb65bed625e2a6cb415821bd0798754ce08" -m "Upstream-Commit: eafdf11a2cea44aabc51ce59bbc031e0aaee9640" -m "Upstream-Commit: 481e0b83d5393419b27b17d95767104c7c1bda26" -m "Upstream-Commit: 6576ef639cbb7be8bc5e6c25134956803d18f8d8"
```

---

### Task 9: Evaluate and import deterministic runtime rollout controls

**Files:**
- Create: `headroom/rollout.py`
- Create: `headroom/cli/rollout.py`
- Create: `crates/headroom-core/src/rollout.rs`
- Modify: proxy/config/CLI integration files touched by `3077ac81`
- Test: `tests/test_rollout.py`
- Test: Rust rollout vector tests

**Interfaces:**
- Consumes: existing config, compression policy, and output shaping.
- Produces: default-off deterministic rollout policies with matching Python and Rust decisions.

- [ ] **Step 1: Apply rollout tests from `3077ac81`; verify RED**

Run Python rollout tests and the Rust core rollout target. Confirm missing rollout APIs cause the failure.

- [ ] **Step 2: Apply production changes and preserve default behavior**

Keep rollout controls disabled when no rollout configuration is present. Do not import the PR-template, governance-script, release metadata, or unrelated documentation hunks from the commit.

- [ ] **Step 3: Verify GREEN and commit**

Run:

```bash
UV_CACHE_DIR=/tmp/headroom-upstream-uv-cache rtk test uv run --extra dev python -m pytest -q tests/test_rollout.py tests/test_compression_policy.py tests/test_output_shaper.py tests/test_output_savings.py
rtk cargo test -p headroom-core rollout
rtk git diff --check
rtk git add -A && rtk git commit -m "feat: add deterministic runtime rollouts" -m "Upstream-Commit: 3077ac81e8ef3ddefebbe308ea37a4e9bb2100e6"
```

---

### Task 10: Dispatch Homebrew after a successful self-hosted Docker build

**Files:**
- Modify: `.github/workflows/docker.yml`
- Modify: `tests/test_release_workflows.py`

**Interfaces:**
- Consumes: successful `docker-manifest` job on a push to `self-hosted` and secret `HOMEBREW_TOOLS_PAT`.
- Produces: cross-repository dispatch of `joshyorko/homebrew-tools/.github/workflows/tap-auto-update.yml` with `slot_id=headroom-daily`.

- [ ] **Step 1: Write a behavior contract test**

Add a workflow test that parses the YAML and requires a dispatch job to depend on `docker-manifest`, run only for successful pushes to `refs/heads/self-hosted`, validate a non-empty `HOMEBREW_TOOLS_PAT`, and call `actions.createWorkflowDispatch` with the exact owner, repository, workflow, ref, and slot.

- [ ] **Step 2: Verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/headroom-upstream-uv-cache rtk test uv run --extra dev python -m pytest -q tests/test_release_workflows.py -k homebrew
```

Expected: failure because no post-Docker Homebrew dispatch job exists.

- [ ] **Step 3: Add the minimal Docker workflow job**

Use pinned `actions/github-script`, `needs: docker-manifest`, least-privilege `contents: read`, the PAT secret, and the existing RCC `createWorkflowDispatch` payload. Do not change the Homebrew receiver.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
UV_CACHE_DIR=/tmp/headroom-upstream-uv-cache rtk test uv run --extra dev python -m pytest -q tests/test_release_workflows.py tests/test_self_hosted_deploy_config.py
rtk git diff --check
rtk git add -A && rtk git commit -m "ci: dispatch Homebrew build after Docker publish"
```

---

### Task 11: Run final repository and packaging verification

**Files:**
- Modify only if a failing test exposes a regression; every fix requires its own failing regression test and commit.

**Interfaces:**
- Consumes: the complete selective reconciliation stack.
- Produces: evidence that the candidate is ready to publish.

- [ ] **Step 1: Run merge-sensitive Python suites**

Run:

```bash
UV_CACHE_DIR=/tmp/headroom-upstream-uv-cache rtk test uv run --extra dev python -m pytest -q tests/test_ccr_tool_always_on.py tests/test_ccr_tool_injection.py tests/test_context_tool_cleanup.py tests/test_openai_codex_ws_lifecycle.py tests/test_proxy_byte_faithful_forwarding.py tests/test_proxy_handler_helpers.py tests/test_proxy_loopback_gating.py tests/test_proxy_project_savings.py tests/test_proxy_settings_endpoints.py tests/test_provider_proxy_routes.py tests/test_provider_openai_realtime.py tests/test_proxy_copilot_auth_hooks.py tests/test_memory_handler_native_ops.py tests/test_self_hosted_deploy_config.py tests/test_release_workflows.py
```

- [ ] **Step 2: Run static and Rust gates**

Run:

```bash
UV_CACHE_DIR=/tmp/headroom-upstream-uv-cache rtk test uv run --extra dev ruff check headroom tests
UV_CACHE_DIR=/tmp/headroom-upstream-uv-cache rtk test uv run --extra dev ruff format --check headroom tests
rtk cargo fmt --all -- --check
rtk cargo test -p headroom-core
rtk cargo test -p headroom-proxy
```

- [ ] **Step 3: Run clean-container and Homebrew gates**

Run:

```bash
rtk dagger call smoke-wheel
rtk test npm --prefix /home/kdlocpanda/syncthing-compose/sync/second_brain/Areas/devcontainers/homebrew-tools/dagger/tap-pipeline test
```

- [ ] **Step 4: Run the full Python suite**

Run the full suite with failures retained. Rerun any order-dependent failures together and individually; do not accept a deterministic failure.

```bash
UV_CACHE_DIR=/tmp/headroom-upstream-uv-cache rtk test uv run --extra dev python -m pytest -q
```

- [ ] **Step 5: Review final history and diff**

Run:

```bash
rtk git status --short --branch
rtk git log --oneline self-hosted..HEAD
rtk git diff --stat self-hosted..HEAD
rtk git diff --check self-hosted..HEAD
```

Expected: clean worktree and only the reviewed reconciliation stack.

---

### Task 12: Publish and verify GitHub plus Homebrew acceptance

**Files:** None locally unless live CI exposes a tested defect.

**Interfaces:**
- Consumes: verified candidate and authorized GitHub credentials.
- Produces: updated `origin/self-hosted`, successful Headroom checks/Docker publish, and successful Homebrew bundle/formula build for the exact source SHA.

- [ ] **Step 1: Confirm identity, remote state, and required secret**

Run read-only identity and ref checks. Require `HOMEBREW_TOOLS_PAT` to exist by name without exposing its value.

- [ ] **Step 2: Publish by fast-forward**

Fetch `origin/self-hosted`, prove it is an ancestor of `HEAD`, then run:

```bash
rtk git push origin HEAD:self-hosted
```

- [ ] **Step 3: Verify Headroom CI and Docker**

Use `ghx` for run discovery and normal `gh` for Actions logs. Require the child jobs, especially `docker-build`, `docker-manifest`, and the Homebrew dispatch job, to conclude successfully.

- [ ] **Step 4: Verify Homebrew receipt and source provenance**

Locate the triggered `Tap Auto Update` run in `joshyorko/homebrew-tools`. Require `headroom-self-hosted` selection, source SHA equal to the pushed Headroom SHA, successful offline bundle and Linuxbrew smoke, formula commit, and release artifact publication.

- [ ] **Step 5: Report the exact published state**

Report final Headroom SHA, retained and excluded upstream groups, Headroom workflow URLs/conclusions, Homebrew workflow URL/conclusion, formula version/source SHA, and any non-product infrastructure exception.
