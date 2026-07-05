# Codex Headroom Setup

Use this guide when a machine already has access to a deployed Headroom proxy.

There are two different jobs:

1. Durable setup: write the Codex provider, MCP servers, and hooks so normal
   Codex sessions use Headroom.
2. One-off launch: start a Codex process from the shell with the Headroom
   runtime environment set for that process.

`headroom init codex` is the normal durable setup command. It does not launch
Codex.

`headroom wrap codex` is the one-off launch command. It starts Codex through
Headroom and sets runtime environment such as `HEADROOM_PROJECT`.

Because Codex loads providers and MCP servers from `config.toml`, `wrap codex`
may still write persistent config before launching. That config must be the same
provider and MCP shape that `init codex` writes. `wrap codex --prepare-only` is
only a compatibility/diagnostic path for applying that same durable setup
without launching Codex.

## Rebuild the Headroom tool

Run this from the Headroom repo root after your proxy deploy is current:

```bash
CC=gcc-16 CXX=g++-16 uv tool install --force --editable '.[proxy]'
```

Verify that the shell is using the rebuilt tool:

```bash
which headroom
headroom --version
headroom init --help | grep -- --proxy-url
```

## Which command to use

Use `init` for setup, repair, and new machines:

```bash
export HEADROOM_PROXY_URL=http://10.10.10.89
headroom init --proxy-url "$HEADROOM_PROXY_URL" codex
```

Run this after installing or rebuilding Headroom, after changing proxy URL, or
from each project repo where you want repo-local `.codex` hooks. This is the
command a new user should run. In the normal setup flow, do not run both
`init codex` and `wrap codex --prepare-only`; use `init codex`.

Use `wrap` when you want to launch one Codex session from the shell:

```bash
headroom wrap codex --proxy-url "$HEADROOM_PROXY_URL"
headroom wrap codex --proxy-url "$HEADROOM_PROXY_URL" -- "fix the bug"
```

This starts Codex immediately. It can also start or target a proxy, set
`HEADROOM_PROJECT`, enable runtime options such as `--memory` or `--learn`, and
pass prompt/CLI args through to Codex.

Use `wrap --prepare-only` only as a compatibility check:

```bash
headroom wrap codex --prepare-only --proxy-url "$HEADROOM_PROXY_URL"
```

This should write the same durable provider/MCP/hooks result as `init codex`,
then exit without launching Codex. Do not use it as the primary documented
setup flow; it exists so old wrap-based setup snippets keep working. If
`init codex` and `wrap codex --prepare-only` produce different persistent
Codex config, that is a Headroom bug.

## Recommended new-machine flow

Run this from the project repo you want Codex to use with Headroom:

```bash
export HEADROOM_PROXY_URL=http://10.10.10.89
headroom init --proxy-url "$HEADROOM_PROXY_URL" codex
```

Serena is installed by default alongside tokensave. `--serena` is accepted for
explicitness and compatibility with older setup snippets; use `--no-serena` to
opt out.

Useful variants:

```bash
headroom init --proxy-url "$HEADROOM_PROXY_URL" codex --no-tokensave
headroom init --proxy-url "$HEADROOM_PROXY_URL" codex --no-serena
headroom init --proxy-url "$HEADROOM_PROXY_URL" codex --code-graph
headroom init -g --proxy-url "$HEADROOM_PROXY_URL" codex
```

`-g` writes user-scope hooks. Without `-g`, provider and MCP config are written
to the Codex user config, while hooks are written into the current repo's
`.codex` directory.

## What changes

### `$CODEX_HOME/config.toml`

If `CODEX_HOME` is unset, this is `~/.codex/config.toml`.

The setup writes one Headroom provider block at the document root:

```toml
# --- Headroom Codex provider ---
model_provider = "headroom"
openai_base_url = "http://10.10.10.89/v1"

[model_providers.headroom]
name = "OpenAI via Headroom proxy"
base_url = "http://10.10.10.89/v1"
supports_websockets = true
requires_openai_auth = true
env_http_headers = { "X-Headroom-Project" = "HEADROOM_PROJECT" }
# --- end Headroom Codex provider ---
```

`requires_openai_auth = true` is only written when Codex auth indicates a
ChatGPT login. API-key users omit that line.

The proxy URL must be the deployed proxy root plus `/v1`:

```toml
openai_base_url = "http://10.10.10.89/v1"
base_url = "http://10.10.10.89/v1"
```

It should not be a project-scoped URL such as
`http://10.10.10.89/p/headroom/v1`.

If the existing provider block already has the same URL, websocket flag, auth
mode, and `X-Headroom-Project` header, setup leaves that config unchanged and
only updates the project-local files that need work.

The setup also registers the Headroom MCP server:

```toml
# --- Headroom MCP server ---
[mcp_servers.headroom]
command = "headroom"
args = ["mcp", "serve"]

[mcp_servers.headroom.env]
HEADROOM_PROXY_URL = "http://10.10.10.89"
# --- end Headroom MCP server ---
```

By default it registers tokensave:

```toml
# --- Headroom MCP server: tokensave ---
[mcp_servers.tokensave]
command = "/var/home/you/.local/bin/tokensave"
args = ["serve"]
# --- end Headroom MCP server: tokensave ---
```

The tokensave command can be an absolute path or `tokensave`, depending on where
the binary is available.

By default, and unless `--no-serena` is passed, it also registers Serena:

```toml
# --- Headroom MCP server: serena ---
[mcp_servers.serena]
command = "uvx"
args = ["--from", "git+https://github.com/oraios/serena", "serena", "start-mcp-server", "--project-from-cwd", "--context", "codex", "--open-web-dashboard", "False"]
# --- end Headroom MCP server: serena ---
```

### `.codex/config.toml`

For local project scope, setup enables Codex hooks in the current repo:

```toml
[features]

# --- Headroom init features ---
hooks = true
# --- end Headroom init features ---
```

If `[features]` already has a user-managed `hooks` key, setup respects it.

### `.codex/hooks.json`

For local project scope, setup writes:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume",
        "hooks": [
          {
            "type": "command",
            "command": "headroom init hook ensure --profile init-headroom-<id> --marker headroom-init-codex",
            "timeout": 15
          },
          {
            "type": "command",
            "command": "headroom mcp report-rtk --proxy-url http://10.10.10.89 --scope project >/dev/null 2>&1 || true # headroom-init-codex-rtk-report",
            "timeout": 15
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "headroom init hook ensure --profile init-headroom-<id> --marker headroom-init-codex",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

The hook command uses the portable `headroom` executable from PATH. It should
not point at a checkout-local `.venv`, an old repo path, or a removed working
tree.

The generated profile id is stable for the current install profile. Re-running
setup should not rewrite `hooks.json` when the content is unchanged. Hook trust
entries in `$CODEX_HOME/config.toml` are pruned only when the hook file content
actually changes.

## Verify

Check the deployed proxy URL:

```bash
grep -n 'model_provider = "headroom"' "$HOME/.codex/config.toml"
grep -n 'openai_base_url = "http://10.10.10.89/v1"' "$HOME/.codex/config.toml"
grep -n 'base_url = "http://10.10.10.89/v1"' "$HOME/.codex/config.toml"
grep -n 'X-Headroom-Project' "$HOME/.codex/config.toml"
```

Check MCP registrations:

```bash
grep -n '\[mcp_servers.headroom\]' "$HOME/.codex/config.toml"
grep -n '\[mcp_servers.tokensave\]' "$HOME/.codex/config.toml"
grep -n '\[mcp_servers.serena\]' "$HOME/.codex/config.toml"
```

Check repo-local hooks:

```bash
grep -n 'hooks = true' .codex/config.toml
grep -n 'headroom init hook ensure' .codex/hooks.json
grep -n 'headroom mcp report-rtk' .codex/hooks.json
```

Report this repo's RTK project savings to the deployed dashboard:

```bash
headroom mcp report-rtk --proxy-url "$HEADROOM_PROXY_URL" --scope project
```

Restart Codex after setup so the provider, MCP servers, and hooks are loaded.
Approve the new hook commands when Codex asks.

## Notes

This setup does not deploy the proxy. If proxy server code changed, run the
Kamal deploy separately before using the rebuilt CLI against that proxy.

The setup command cleans old Headroom init and old `wrap codex` provider marker
blocks, but it should not remove unrelated user-managed provider tables.
