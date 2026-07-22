# Rebuild Tool Bootstrap Design

## Goal

Make `scripts/headroom-rebuild-install` self-bootstrapping on Josh's Bluefin host when either the Dagger CLI or `uv` is absent.

## Behavior

- Preserve the existing argument validation and rebuild/install sequence.
- Before rebuilding, check for `dagger` and `uv` independently.
- If either command is missing, require an available `brew` command and install only that missing formula with `brew install <formula>`.
- Recheck the command after Homebrew returns successfully. Exit with a clear error if it remains unavailable.
- If Homebrew itself is unavailable, exit without attempting another installation method or mutating the host through a different package manager.
- Do not invoke Homebrew when both commands already exist.

## Boundaries

- This is explicitly a Bluefin-host bootstrap path; it does not add `dnf`, `rpm-ostree`, curl installers, or container-side package installation.
- It does not change the Dagger build, wheel export, `uv` tool installation, CLI packaging, or Kamal deployment behavior.
- Homebrew output and exit status remain visible to the operator.

## Verification

Add shell-level regression coverage that runs the script with a temporary fake `PATH` and stub executables. Tests will prove:

1. Existing `dagger` and `uv` skip Homebrew.
2. Missing Dagger invokes `brew install dagger` and continues.
3. Missing `uv` invokes `brew install uv` and continues.
4. Missing Homebrew fails clearly before the build.
5. A successful Homebrew command that does not expose the installed CLI still fails clearly.

The test harness must stub destructive/build commands, so verification never installs host software or performs a real Dagger build.
