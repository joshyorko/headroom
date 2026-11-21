# Rebuild Tool Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `scripts/headroom-rebuild-install` install missing Dagger and `uv` CLIs through Homebrew before rebuilding Headroom.

**Architecture:** Keep bootstrap logic inside the existing host script as one `ensure_brew_tool` shell function. Exercise the real script from pytest inside a temporary fake repository and fake `PATH`, with stub Homebrew, Dagger, and installer commands so tests never mutate the host or perform a build.

**Tech Stack:** Bash, Homebrew CLI, pytest subprocess tests.

## Global Constraints

- Bluefin host bootstrap uses Homebrew only.
- Install only missing `dagger` or `uv` formulae.
- Do not invoke Homebrew when both commands exist.
- Fail clearly if Homebrew is absent or installation does not expose the command.
- Preserve existing Dagger build, wheel export, host install, and argument behavior.

---

### Task 1: Tool bootstrap behavior

**Files:**
- Create: `tests/test_headroom_rebuild_install_script.py`
- Modify: `scripts/headroom-rebuild-install`

**Interfaces:**
- Consumes: host `command -v`, `brew install <formula>`.
- Produces: `ensure_brew_tool <command> <formula>`, returning success only when the command is available.

- [ ] **Step 1: Write the failing subprocess tests**

Create a temporary repository containing the real script. Add fake executables that record calls and simulate the Dagger export/install sequence. Assert these cases: both tools present skips Homebrew; missing Dagger installs `dagger`; missing `uv` installs `uv`; missing Homebrew exits 127; and successful Homebrew without a new command exits 127.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run --no-sync --with pytest python -m pytest tests/test_headroom_rebuild_install_script.py -q
```

Expected: missing-tool installation cases fail because the current script exits immediately.

- [ ] **Step 3: Implement the minimal bootstrap function**

Add this behavior before the build:

```bash
ensure_brew_tool() {
  local command_name="$1"
  local formula="$2"
  if command -v "$command_name" >/dev/null 2>&1; then
    return 0
  fi
  if ! command -v brew >/dev/null 2>&1; then
    echo "$command_name is missing and Homebrew is required to install it." >&2
    return 127
  fi
  echo "Installing missing $command_name CLI with Homebrew..."
  brew install "$formula"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Homebrew completed, but $command_name is still unavailable on PATH." >&2
    return 127
  fi
}
```

Call it as `ensure_brew_tool dagger dagger` and `ensure_brew_tool uv uv`.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run the Step 2 command. Expected: all five tests pass.

- [ ] **Step 5: Run shell/static verification**

```bash
bash -n scripts/headroom-rebuild-install
uv run --no-sync --with pytest python -m pytest tests/test_headroom_rebuild_install_script.py -q
ruff check tests/test_headroom_rebuild_install_script.py
ruff format --check tests/test_headroom_rebuild_install_script.py
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 6: Commit implementation**

```bash
git add scripts/headroom-rebuild-install tests/test_headroom_rebuild_install_script.py
git commit -m "fix: bootstrap rebuild tool dependencies"
```

### Task 2: Guarded publication

**Files:** No additional file changes.

**Interfaces:**
- Consumes: verified integration HEAD and live `origin/self-hosted`.
- Produces: fast-forward update of `origin/self-hosted` without force.

- [ ] **Step 1: Fetch and verify ancestry**

```bash
git fetch origin self-hosted
git merge-base --is-ancestor origin/self-hosted HEAD
```

Expected: both commands exit 0.

- [ ] **Step 2: Push normally**

```bash
git push origin HEAD:refs/heads/self-hosted
```

Expected: remote advances without force.

- [ ] **Step 3: Verify remote and cleanliness**

```bash
git fetch origin self-hosted
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/self-hosted)"
git status --porcelain=v1 --untracked-files=all
```

Expected: SHAs match and status output is empty.
