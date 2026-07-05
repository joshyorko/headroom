# Headroom Dagger Automation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Provide a repo-local Dagger/MCP automation surface for rebuilding, smoke-testing, and reinstalling the Headroom CLI without depending on the Bluefin host toolchain.

**Architecture:** Dagger owns build and smoke-test containers. Host mutation stays explicit through an exported install script. Kamal deploy remains a host-side handoff through the existing `bin/kamal` workflow.

**Tech Stack:** Dagger Python SDK, Docker, uv, maturin, Rust 1.95, Codex MCP.

---

### Task 1: Repo-Local Dagger MCP Bridge

**Files:**
- `dagger.json`
- `.dagger/src/headroom_builder/main.py`
- `.dagger/src/headroom_builder/__init__.py`
- `scripts/headroom-dagger-mcp`
- `scripts/headroom-dagger-mcp-filter.py`
- `scripts/headroom-rebuild-install`
- `.gitignore`
- `docs/headroom-dagger-mcp.md`

- [ ] Use the RCC-style launcher pattern: current directory wins when it has `dagger.json` and `.dagger/`; `HEADROOM_DAGGER_REPO` pins a checkout only when needed.
- [ ] Keep the stdout filter so Dagger progress logs go to stderr and MCP JSON stays on stdout.
- [ ] Allowlist the Dagger MCP launcher scripts and `scripts/headroom-rebuild-install` in `.gitignore`; keep unrelated private scripts ignored.
- [ ] Exclude `.git`, `.venv`, `.env`, `.env.*`, `.kamal/secrets`, `target`, `dist`, and caches from Dagger source uploads.
- [ ] Verify `scripts/headroom-dagger-mcp --help` and `dagger functions`.

### Task 2: Build, Smoke, And Install Primitives

**Files:**
- `.dagger/src/headroom_builder/main.py`
- `scripts/headroom-rebuild-install`
- `docs/headroom-dagger-mcp.md`

- [ ] Expose only `build-wheel`, `smoke-wheel`, and `dev-install-script` in v1.
- [ ] Build wheels with Python 3.11, Rust 1.95, `uv==0.11.18`, and `maturin>=1.5,<2.0`.
- [ ] Make `smoke-wheel` install the built wheel in a clean venv and verify `headroom._core` plus `headroom --version`.
- [ ] Make `dev-install-script` export `dist/*.whl` plus `install-headroom-from-wheel`, which runs `uv tool install --force --python 3.11`.
- [ ] Add `scripts/headroom-rebuild-install` as the primary host command. It removes `dist/headroom-dev`, runs `dagger call dev-install-script export --path dist/headroom-dev`, then runs `dist/headroom-dev/install-headroom-from-wheel`.
- [ ] Verify `dagger call smoke-wheel` and `scripts/headroom-rebuild-install`.

### Task 3: Repo-Local Codex Wiring

**Files:**
- `.codex/config.toml`
- `.codex/hooks.json`
- `docs/headroom-dagger-mcp.md`

- [ ] Register `[mcp_servers.headroom-dagger]` in `.codex/config.toml`; do not use global `codex mcp add` for this bridge.
- [ ] Keep hooks enabled in `.codex/config.toml`.
- [ ] Require a fast non-mutating `SessionStart` hook that checks `scripts/headroom-dagger-mcp --help` and confirms the repo-local MCP registration exists.
- [ ] Do not rebuild, run Dagger, or deploy from hooks.

### Task 4: Kamal Handoff

**Files:**
- `docs/headroom-dagger-mcp.md`

- [ ] Document `bin/kamal deploy`, `/readyz`, and `bin/kamal logs` as the post-build deploy handoff.
- [ ] Do not expose live Kamal deploy through Dagger in v1.
- [ ] Do not copy SSH keys, mount SSH sockets, or move `.env.kamal.local` into Dagger in v1.

### Task 5: Final Verification

- [ ] Parse `.codex/config.toml` and `.codex/hooks.json`.
- [ ] Run the required hook command by hand.
- [ ] Run `dagger functions` and confirm only the three v1 methods are exposed.
- [ ] Run `dagger call smoke-wheel`.
- [ ] Run `scripts/headroom-rebuild-install`.
- [ ] Confirm `headroom --version` works from PATH.
