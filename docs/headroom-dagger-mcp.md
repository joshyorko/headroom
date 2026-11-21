# Headroom Dagger MCP

This repo includes a small Dagger module for building Headroom from the active
checkout in a containerized Linux environment. The MCP launcher mirrors the RCC
Dagger bridge pattern: Codex starts one script, the script selects the current
Dagger module or a pinned checkout, and Dagger exposes module functions through
MCP.

## Register With Codex

Prefer the repo-local Codex config so this MCP server is only active while
working in this checkout. Add this to `.codex/config.toml`:

```toml
[mcp_servers.headroom-dagger]
command = "/var/home/kdlocpanda/second_brain/Resources/Sandbox/headroom_perf/headroom/scripts/headroom-dagger-mcp"
```

Use the pinned env form only when Codex may start outside this checkout but
should still expose this Headroom module:

```toml
[mcp_servers.headroom-dagger]
command = "/var/home/kdlocpanda/second_brain/Resources/Sandbox/headroom_perf/headroom/scripts/headroom-dagger-mcp"

[mcp_servers.headroom-dagger.env]
HEADROOM_DAGGER_REPO = "/var/home/kdlocpanda/second_brain/Resources/Sandbox/headroom_perf/headroom"
```

Avoid `codex mcp add` for this bridge unless you intentionally want a global
registration that follows you outside this repo. Codex loads MCP server
definitions when a session starts, so start a new Codex session after changing
`.codex/config.toml`.

## Required Hooks

This repo requires Codex hooks for cheap repo-local diagnostics. Keep them fast
and non-mutating: do not rebuild Headroom, run Dagger, or deploy from a startup
hook.

`.codex/config.toml` should have hooks enabled:

```toml
[features]
hooks = true
```

`.codex/hooks.json` must include a `SessionStart` check that verifies the bridge
script works and that the MCP server is registered in `.codex/config.toml`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume",
        "hooks": [
          {
            "type": "command",
            "command": "scripts/headroom-dagger-mcp --help >/dev/null 2>&1 && grep -q '^\\[mcp_servers\\.headroom-dagger\\]' .codex/config.toml || echo 'headroom-dagger MCP bridge is not registered in .codex/config.toml' >&2 # headroom-dagger-mcp-check",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

If `.codex/hooks.json` already contains Headroom hooks, add only the command
entry instead of replacing the whole file.

## Manual Use

Rebuild Headroom in Dagger, install the fresh CLI on the Bluefin host PATH, and
verify it:

```bash
scripts/headroom-rebuild-install
```

This is the primary command for agents and humans after local code changes. It
exports a Dagger-built wheel under `dist/headroom-dev`, runs the generated host
installer, and finishes with `headroom --version`.

List available functions:

```bash
dagger functions
```

Build a wheel from this checkout:

```bash
dagger call build-wheel export --path dist/dagger
```

Build and smoke-test the wheel inside Dagger:

```bash
dagger call smoke-wheel
```

Build a wheel plus a host-side installer script:

```bash
dagger call dev-install-script export --path dist/headroom-dev
dist/headroom-dev/install-headroom-from-wheel
```

That lower-level path is what `scripts/headroom-rebuild-install` wraps. The
install script uses `uv tool install --force --python 3.11` against the freshly
built wheel, refreshes uv shell setup, exports uv's tool bin directory for the
current process, then runs `headroom --version`.

Hand off to the existing Kamal deploy flow when you are ready to mutate the
remote VM:

```bash
bin/kamal deploy
curl -fsS "http://${KAMAL_PUBLIC_HOST}/readyz"
bin/kamal logs
```

Kamal remains host-side in v1 so SSH keys, Docker socket access, and deploy
secrets stay in the existing `.env.kamal.local`, `.kamal/secrets`, and
`bin/kamal` boundary.

## MCP Surface

Dagger's MCP server exposes a generic method interface:

- `ListMethods`
- `SelectMethods`
- `CallMethod`
- `ChainMethods`
- `ReadLogs`

Useful Headroom module methods:

| Method | Use |
| --- | --- |
| `build-wheel` | Build a wheel from the active checkout and return `dist/`. |
| `smoke-wheel` | Build the wheel, install it in a clean venv, and run import/CLI smoke checks. |
| `dev-install-script` | Return `dist/` plus a host-side installer script for `uv tool install`. |

## Runtime Boundary

- Host: Codex starts `scripts/headroom-dagger-mcp`.
- Dagger: builds from the current directory when it contains `dagger.json` and
  `.dagger/`, or from `HEADROOM_DAGGER_REPO` when pinned.
- Host install: explicit. Dagger exports a wheel and script; the script mutates
  the user tool install on the host. Use `scripts/headroom-rebuild-install` for
  the complete build-export-install-verification flow.
- Deploy: explicit. Use the repo's existing Kamal wrapper from the host; Dagger
  does not copy SSH keys, mount SSH sockets, or deploy in v1.

If Docker or Dagger is unavailable, do not block on this bridge. Use the normal
checkout command instead:

```bash
CC=gcc-16 CXX=g++-16 uv tool install --force --editable '.[proxy]'
```
