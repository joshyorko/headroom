# RCC/HoloTree RTK Runtime Design

> **Deferred:** Headroom currently relies on an independently installed, PATH-discovered RTK
> (Homebrew on the primary workstation). This document is retained as historical design material
> and does not define the current release implementation.

**Status:** Proposed for implementation after user review  
**Target:** `self-hosted` branch  
**Primary platform:** Bluefin/Linux `linux_amd64`  
**Runtime package:** `rtk-cli=0.44.2` from Conda Forge

## Purpose

Headroom's self-hosted product depends on RTK to reduce command output before it enters an
agent's context. Upstream Headroom removed its RTK integration because it downloaded and
managed a third-party binary, rewrote agent commands, mixed RTK savings into Headroom's own
product measurements, and could not safely distinguish Headroom-owned artifacts from
user-owned installations.

The self-hosted product still needs three RTK capabilities:

1. Agents receive durable repo-level instructions to use RTK.
2. RTK runs at native speed without RCC or Python in the command hot path.
3. Project-scoped RTK savings are reported from the workstation to the remote Headroom proxy.

This design restores those capabilities without restoring upstream's downloader, automatic
command rewriting, proxy-side RTK execution, or destructive cleanup of user-owned files.

## Evidence and Current Regression

The current checkout contains a half-retired RTK integration:

- `headroom/cli/init.py::_ensure_codex_hooks` writes local runtime hooks only when the proxy
  host is loopback. For a remote proxy it sets both desired Headroom hook events to `None`,
  removing existing Headroom-managed repo hooks.
- `headroom/cli/mcp.py::mcp_report_rtk` still imports `headroom.rtk.get_rtk_path`, but upstream
  deleted the `headroom.rtk` package. The installed command therefore fails with
  `ModuleNotFoundError`.
- `headroom/cli/wrap.py` retains the RTK instruction block but no active RTK instruction
  injection path.
- `headroom/context_tool_cleanup.py` still removes RTK launchers, hooks, and instruction
  blocks as retired artifacts.

The exact user command is valid and must remain valid:

```zsh
export HEADROOM_PROXY_URL=http://10.10.10.89
headroom init --proxy-url "$HEADROOM_PROXY_URL" codex --serena
```

For local scope, it must write repo-level Codex configuration. A remote proxy changes which
hooks are needed; it must not mean "delete all Headroom hooks."

RCC feasibility has been proven on the Bluefin host:

- RCC `v18.18.1` resolved the supplied `conda.yaml` into HoloTree environment hash
  `46ee2cfa4c00d5ab`.
- The resolved binary reports `rtk 0.44.2`.
- Direct HoloTree RTK startup and the current Homebrew RTK startup were both below the
  measurement command's 10 ms resolution.
- Calling `rcc task script` for each command added approximately 200-220 ms and is rejected
  for the hot path.
- The Conda Forge recipe builds `rtk-ai/rtk` from a SHA-256-verified source archive, uses
  locked Cargo dependencies, produces auditable binaries, and tests the installed `rtk`
  executable.

## Product Decisions

### Headroom owns the integration, not RTK installation internals

Headroom owns the pinned runtime declaration, RCC resolution, launcher provenance, agent
instructions, health checks, and remote reporting. RCC owns environment creation and cache
lifecycle. Conda Forge owns the reproducible RTK package. RTK owns command filtering and its
counters.

Headroom does not download RTK release binaries, invoke `rtk init`, register RTK's command
rewrite hooks, or run RTK inside the Headroom proxy.

### Managed RTK is default-on for self-hosted Codex init

On a supported platform, `headroom init codex` resolves the pinned RTK runtime, installs the
Headroom-owned launcher, injects repo instructions, and installs the RTK session hook.
`--no-rtk` explicitly opts out and removes only artifacts carrying the new Headroom ownership
markers.

This default belongs only to the self-hosted product. It is not proposed for upstream
Headroom.

### RCC is never in the command hot path

RCC runs only during explicit init, version changes, or repair. Normal command execution is:

```text
agent -> ~/.local/bin/rtk -> exec HoloTree rtk -> requested command
```

The launcher is a small native shell shim. It does not start Headroom, Python, RCC, Conda, an
Action Server, or a daemon.

### HoloTree isolation is dependency isolation, not a security sandbox

The HoloTree keeps the RTK binary and its runtime libraries out of the user's Python and host
package environments. RTK still executes commands in the repository with the user's normal
permissions. Documentation and CLI output must say this plainly.

## Scope

### In scope

- A pinned RCC/HoloTree RTK runtime for `linux_amd64`.
- A direct Headroom-owned `rtk` launcher with provenance metadata.
- Idempotent repo-level RTK instructions.
- Local and remote Codex SessionStart behavior.
- Project-scoped RTK reporting to `/stats/context-tool`.
- Safe migration from the half-retired self-hosted state.
- Focused unit, integration, and performance tests.
- A future-compatible manifest shape for additional platforms.

### Out of scope

- Restoring upstream's RTK downloader or `headroom/rtk/installer.py`.
- `rtk init`, `--auto-patch`, PreToolUse command rewriting, or generated RTK hook scripts.
- Installing RCC automatically or mutating the Bluefin base OS.
- Running RCC, Python, or HTTP reporting for each RTK command.
- Running RTK inside the remote proxy or app container.
- Counting RTK savings as Headroom proxy compression savings.
- Supporting unverified platforms in the first implementation.
- A general-purpose HoloTree runtime framework for arbitrary tools.
- Action Server, a local RTK service, or a long-lived runner process.

## Architecture

### Packaged runtime declaration

Add a package-data directory:

```text
headroom/resources/rtk-runtime/
  robot.yaml
  conda.yaml
  environment_linux_amd64_freeze.yaml
```

The production `conda.yaml` contains only the required binary:

```yaml
channels:
  - conda-forge

dependencies:
  - rtk-cli=0.44.2
```

Python and `uv` from the feasibility fixture are not runtime requirements and must not be
included. `robot.yaml` exists as RCC's stable environment descriptor and exposes only a
diagnostic `Verify` task that runs `rtk --version`; normal execution does not use the task.

The Linux freeze file is generated from an actual resolved run and committed. Additional
platform freeze files are added only after the same acceptance suite passes on those
platforms. Hololib archives are optional build/cache artifacts, not source of truth and not
committed by default.

### Python modules

```text
headroom/rtk_runtime/
  __init__.py
  manifest.py
  rcc.py
  state.py
  launcher.py
  instructions.py
  reporting.py
```

`manifest.py`

- Locates packaged runtime resources.
- Computes a stable digest across `robot.yaml`, selected freeze file, and fallback
  `conda.yaml`.
- Defines the expected RTK version and supported platform identifiers.
- Returns immutable runtime requirements; it performs no writes or subprocess work.

`rcc.py`

- Locates `rcc` with `shutil.which`.
- Runs RCC with a sanitized environment: remove `VIRTUAL_ENV`, `PYTHONHOME`, and
  `PYTHONPATH`; set `ROBOCORP_HOME` to the dedicated RTK RCC home.
- Resolves HoloTree variables from the packaged robot descriptor.
- Parses RCC JSON and validates `CONDA_PREFIX`, the HoloTree space, the RTK executable, and
  `rtk --version`.
- Uses a bounded file lock so concurrent init/session repair cannot build the same environment
  simultaneously.
- Returns structured errors; it never edits agent config.

`state.py`

- Stores the resolved runtime snapshot atomically at
  `~/.headroom/runtimes/rtk/runtime.json`, respecting `HEADROOM_WORKSPACE_DIR`.
- Uses a dedicated RCC home at `~/.headroom/runtimes/rtk/rcc-home`, with an explicit
  `HEADROOM_RTK_RCC_HOME` override for operators.
- Validates cached state before reuse.

The snapshot schema is:

```json
{
  "schema_version": 1,
  "manifest_digest": "...",
  "platform": "linux_amd64",
  "rcc_version": "v18.18.1",
  "rcc_home": ".../rcc-home",
  "holotree_space": "...",
  "conda_prefix": "...",
  "rtk_executable": ".../bin/rtk",
  "rtk_version": "0.44.2",
  "resolved_at": "..."
}
```

A cache hit requires all of the following:

- schema, manifest digest, platform, RCC version, and RCC home match;
- the recorded HoloTree root and RTK executable still exist;
- the executable is runnable;
- `rtk --version` reports the pinned version.

`launcher.py`

- Installs `~/.local/bin/rtk` on Unix only when the path is absent or already carries the new
  Headroom ownership marker.
- Refuses to overwrite a regular file or symlink that is not Headroom-owned.
- Writes atomically and preserves no stale target.
- Generates a POSIX shell launcher that checks the resolved executable and then uses `exec`.
- On a missing target, exits `127` with the exact repair command; it never invokes RCC itself.

Example shape:

```sh
#!/bin/sh
# headroom-managed-rtk-launcher schema=1 version=0.44.2
target='/absolute/holo/tree/bin/rtk'
if [ ! -x "$target" ]; then
  echo 'Headroom RTK runtime is missing; run: headroom init codex' >&2
  exit 127
fi
exec "$target" "$@"
```

`instructions.py`

- Owns the concise RTK instruction text currently stranded in `cli/wrap.py`.
- Writes a new marker pair, `headroom:managed-rtk-instructions-v2`, into the repo-level
  `AGENTS.md` used by Codex.
- Replaces an exact legacy Headroom RTK block with the new block.
- Never removes or rewrites surrounding user content.
- Removes only the v2 block when `--no-rtk` is requested.

`reporting.py`

- Resolves RTK from a valid managed snapshot.
- Supports a PATH fallback only for the narrow compatibility command described below; managed
  init never treats an arbitrary PATH executable as the pinned runtime.
- Runs `rtk gain [--project] --format json` with a bounded timeout.
- Posts the existing payload contract to `<proxy-root>/stats/context-tool`.
- Keeps RTK savings in the context-tool/reporting layer, separate from proxy compression.
- Returns structured success/failure data so hooks can suppress output while explicit CLI
  calls can display actionable errors.

## Init and Hook Behavior

### Ordering and transactional boundary

`headroom init codex` performs operations in this order:

1. Resolve and validate the RTK runtime.
2. Validate launcher ownership/collision policy.
3. Prepare all intended config mutations in memory.
4. Write the launcher and runtime snapshot atomically.
5. Write repo instructions atomically.
6. Merge Codex provider, MCP, feature, and hook configuration.

If RCC is missing, the platform is unsupported, resolution fails, or a user-owned launcher
collides, init stops before modifying Codex or instruction files. Existing valid Headroom
configuration is left untouched.

### Separate hook ownership markers

Replace the overloaded `headroom-init-codex` identity with two explicit markers:

- `headroom-init-codex-runtime` for the local Headroom proxy watchdog.
- `headroom-init-codex-rtk` for RTK health/reporting.

The hook merger deduplicates each marker independently and preserves every unrelated hook.

### Local proxy

Repo `.codex/hooks.json` contains:

- `SessionStart startup|resume`: local runtime ensure followed by RTK health/reporting.
- `PreToolUse Bash`: local runtime ensure only.

RTK is not invoked by PreToolUse. Agents voluntarily use the direct launcher because of the
repo instructions.

### Remote proxy

Repo `.codex/hooks.json` contains:

- `SessionStart startup|resume`: RTK health/reporting only.
- No Headroom `PreToolUse` entry.

The SessionStart command receives the proxy root, not `/v1`, and runs a hidden command such as:

```text
headroom init hook rtk --proxy-url http://10.10.10.89 --marker headroom-init-codex-rtk
```

The hook first validates the cached snapshot and launcher without invoking RCC. If invalid, it
attempts one locked, bounded repair. Reporting then runs best-effort. All hook output is
suppressed so it cannot corrupt the agent hook protocol.

### Time bounds and failure behavior

- Warm snapshot/launcher validation target: under 100 ms and no RCC subprocess.
- RTK reporting timeout: 5 seconds, best-effort.
- HoloTree repair timeout: explicit and bounded; initial recommendation 120 seconds.
- A hook repair/report failure never blocks Codex startup and never deletes current state.
- Explicit `headroom init` remains strict and exits nonzero on runtime setup failure.

## User-Owned Artifact Safety

The new integration uses positive ownership markers. Names alone never prove ownership.

- Never overwrite or delete a launcher without the exact v2 marker.
- Never remove a hook without the exact Headroom marker.
- Never remove instructions outside the exact v2 fenced block.
- Never delete a HoloTree or RCC home outside the configured Headroom RTK root.
- `unwrap` removes the v2 launcher only if its target and marker match the recorded snapshot.
- A pre-existing Homebrew, Conda, Cargo, mise, or manually installed RTK remains untouched.
- If a user-owned `~/.local/bin/rtk` blocks the managed launcher, init fails with choices:
  keep the existing installation with `--no-rtk`, move it manually, or explicitly adopt the
  managed runtime after resolving the collision. There is no force-delete flag.

`context_tool_cleanup.py` becomes a versioned legacy migration. It must stop scanning and
deleting by generic RTK names on every wrap/unwrap. The migration may remove only artifacts
whose provenance matches a known old Headroom-managed path or exact old Headroom content. It
must never recognize the v2 markers as retired.

## CLI Surface

### Existing command preserved

```text
headroom mcp report-rtk --proxy-url <proxy-root> --scope project
```

This remains an explicit diagnostics/refresh command. It uses the managed runtime when valid,
then falls back to `shutil.which("rtk")` for backward compatibility. PATH fallback is reported
as unmanaged and is never persisted as the managed runtime.

### Init options

```text
headroom init codex [--no-rtk] [--serena | --no-serena]
```

RTK is default-on for the self-hosted branch. `--no-rtk` removes only v2-managed repo
instructions, RTK hooks, snapshot, and launcher. It does not remove RCC globally, delete
user-owned RTK, or delete unrelated HoloTrees.

### Diagnostics

Add:

```text
headroom rtk status [--json]
headroom rtk repair
```

`status` is read-only and reports manifest version, cache validity, launcher ownership, exact
binary path/version, RCC availability, and last report status. `repair` performs the same
strict runtime reconciliation as init without changing Codex provider or MCP configuration.

There is no `headroom rtk <arbitrary command>` proxy because that would add Python startup to
the hot path.

## Narrow Regression Repair

The conversation contains explicit authorization to "at least fix" the current regression.
That authorization is narrower than approval for the full RCC redesign.

The independently shippable repair is exactly:

1. Change `mcp report-rtk` to resolve an independently installed RTK with `shutil.which`
   instead of importing the deleted `headroom.rtk` package.
2. For remote Codex init, install a repo `SessionStart` report hook using the existing
   `mcp report-rtk` command and proxy root.
3. Keep remote `PreToolUse` absent and keep local runtime watchdog behavior unchanged.
4. Preserve unrelated hooks and existing repo instructions.
5. Add focused tests for the command resolver, remote hook write/merge/idempotence, local hook
   behavior, and explicit report failure.

It does not install RTK, introduce RCC, change cleanup, add instructions, or claim the full
managed-runtime contract. It may ship before the RCC implementation if immediate reporting is
more important than avoiding a short-lived compatibility path.

No code change should combine this repair with the full runtime implementation unless the
implementation plan explicitly sequences and tests both phases.

## Migration Plan

### Phase 0: narrow regression repair

Restore functional PATH-based reporting and the remote SessionStart report hook. This phase is
authorized but remains unimplemented in this design task.

### Phase 1: Linux managed runtime

- Promote the proven runtime descriptor into package resources, reduced to `rtk-cli=0.44.2`.
- Generate and verify the Linux freeze file.
- Implement resolution, state, launcher, instructions, reporting, and diagnostics.
- Replace the Phase 0 hook command with `init hook rtk`.
- Convert legacy cleanup to provenance-based one-time migration.

### Phase 2: additional platforms

For each platform, resolve the Conda Forge package, generate a freeze file, run the complete
acceptance suite, verify launcher semantics, and only then add it to the supported platform
map. Unsupported platforms continue to fail before config mutation unless `--no-rtk` is used.

### Phase 3: optional Hololib distribution

Add reproducible per-platform Hololib export artifacts only if offline/bootstrap latency
justifies them. Build and import must use the same `ROBOCORP_HOME` contract. Hololib remains a
cache/distribution optimization, not the runtime manifest or integrity authority.

## Testing Strategy

### Unit tests

- Manifest digest changes for every runtime descriptor change.
- Platform selection and unsupported-platform errors.
- RCC environment sanitization and dedicated home selection.
- RCC JSON parsing and malformed/missing field errors.
- Cache validation covers every schema field and missing executable.
- Version mismatch invalidates the cache.
- Launcher creation, atomic replacement, quoting, missing target, and collision refusal.
- Instruction migration, idempotence, exact removal, and preservation of user content.
- Managed and PATH-fallback RTK resolution.
- Reporting payload, project cwd, timeout, invalid JSON, and HTTP failure.
- Hook merging preserves unrelated entries and independently deduplicates both markers.
- Legacy cleanup ignores every v2 artifact and preserves user-owned installations.

### Integration tests

- Build the Linux runtime in an isolated `ROBOCORP_HOME`.
- Resolve twice and prove the warm path reuses the same HoloTree without rebuilding.
- Execute the generated launcher and compare `rtk --version` with the pin.
- Delete or invalidate the HoloTree target, run repair, and prove the launcher works again.
- Run local init and assert local runtime plus RTK hooks.
- Run remote init and assert only the RTK SessionStart hook.
- Run `mcp report-rtk` against a test server and confirm project attribution.
- Run init twice and prove byte-idempotent managed files.
- Plant user-owned launchers, hooks, and instructions and prove they survive.

### Performance gates

- Generated launcher overhead is less than 5 ms versus direct HoloTree RTK execution.
- Warm SessionStart validation is less than 100 ms and spawns no RCC process.
- No normal `rtk <command>` path imports or launches Headroom/Python.
- RCC is invoked only for missing, invalid, or changed runtime state.

### Release gates

- Focused pytest suites for all touched modules.
- Ruff check and format check on touched Python files.
- Package-data test proves runtime descriptors ship in wheel and sdist.
- `rcc ht vars` and `rtk --version` acceptance on supported platforms.
- `git diff --check`.
- Disposable-home end-to-end init, report, repair, opt-out, and unwrap checks.

## Observability

Record runtime lifecycle events separately from RTK savings:

- runtime resolution source: cache or RCC;
- manifest digest and RTK version;
- resolve/repair duration and outcome;
- launcher ownership/collision state;
- report timestamp, scope, destination, and outcome;
- no command arguments, command output, repository contents, or secrets.

The remote `/stats` contract continues to identify these values as RTK/context-tool savings,
not Headroom proxy compression savings.

## Rollback

Rollback removes only v2-managed hooks, instructions, launcher, and runtime snapshot. It leaves
the dedicated RCC home intact by default so rollback is fast and non-destructive. An explicit
future cache-clean command may surgically remove that single Headroom RTK RCC home after
verifying ownership and no active lock.

After rollback, `mcp report-rtk` may still use a user-installed RTK through PATH. Remote proxy,
provider, MCP, Serena, and all unrelated Codex configuration remain unchanged.

## Implementation Sequence

1. Ship or explicitly defer the narrow regression repair.
2. Add failing tests for runtime state, launcher safety, and remote/local hook contracts.
3. Add packaged runtime descriptors and package-data verification.
4. Implement manifest, RCC resolution, and state cache.
5. Implement the direct launcher and collision policy.
6. Implement v2 instructions and provenance-safe legacy migration.
7. Integrate reporting and split hook markers.
8. Wire strict init, diagnostics, repair, and opt-out.
9. Run isolated HoloTree, disposable-home, performance, and packaging gates.
10. Rebuild the workstation install; deployment of the remote proxy is required only if the
    server-side `/stats/context-tool` contract changes.

## Decisions Requiring User Review

This specification recommends and fixes the following behavior for implementation:

- Managed RTK is default-on for self-hosted Codex init.
- Linux `linux_amd64` is the only initially supported managed platform.
- Existing user-owned `~/.local/bin/rtk` causes a safe refusal, never overwrite or deletion.
- RCC is required for managed setup but never automatically installed.
- The narrow reporting repair may ship independently before the managed runtime.

Implementation planning starts only after the user approves or revises these decisions.
