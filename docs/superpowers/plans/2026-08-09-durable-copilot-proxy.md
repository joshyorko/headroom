# Durable Copilot Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make plain GitHub Copilot CLI durably use a remote Headroom proxy with subscription authentication and token refresh.

**Architecture:** Durable init writes an encoded Copilot upstream and non-secret bearer seed. The deployed proxy owns the reusable OAuth credential and replaces that seed with refreshed Copilot API tokens. Tracked repository instructions are excluded from retired-tool cleanup.

**Tech Stack:** Python, Click, pytest, Kamal, zsh

## Global Constraints

- Preserve unrelated worktree changes and the untracked `check-conda-packages-runer-feasibility/` directory.
- Keep real OAuth values out of committed files and command output.
- Use repo-native `uv`, Dagger rebuild, and Kamal wrappers.

---

### Task 1: Durable remote Copilot initialization

**Files:**
- Modify: `headroom/cli/init.py`
- Test: `tests/test_cli/test_init_cli.py`

- [ ] Add a failing test for encoded remote Copilot subscription environment.
- [ ] Run the focused test and confirm the existing BYOK environment fails it.
- [ ] Implement remote subscription environment generation with a non-secret bearer seed.
- [ ] Run focused init tests.

### Task 2: Safe retired-tool cleanup

**Files:**
- Modify: `headroom/context_tool_cleanup.py`
- Test: `tests/test_context_tool_cleanup.py`

- [ ] Add a failing test using a real temporary Git repository with a tracked instruction file.
- [ ] Confirm cleanup deletes the tracked file's marker under current behavior.
- [ ] Skip marker cleanup for files tracked by the enclosing Git repository.
- [ ] Run focused cleanup tests.

### Task 3: Remote proxy secret and routing deployment

**Files:**
- Modify: `config/deploy.yml`
- Modify: `.env.kamal.local.example`
- Modify locally only: ignored Kamal secret input

- [ ] Declare the reusable Copilot refresh token as a Kamal secret.
- [ ] Configure the public Copilot API as the proxy's OpenAI target.
- [ ] Populate the ignored local secret from Headroom's saved OAuth credential without printing it.
- [ ] Render and validate Kamal configuration.

### Task 4: Verify, install, deploy, and accept

**Files:**
- Existing modified wrapper routing and regression test.

- [ ] Run focused Copilot, init, cleanup, lint, and formatting checks.
- [ ] Rebuild and install the host CLI with `scripts/headroom-rebuild-install`.
- [ ] Deploy through `bin/kamal deploy` and verify `bin/kamal ready` plus `/readyz`.
- [ ] Run durable init against `http://10.10.10.89`.
- [ ] Verify a clean shell has the intended variables and plain `copilot` returns `ok` through Headroom.
- [ ] Inspect final diff and commit only intended tracked changes.
