from typing import Annotated

import dagger
from dagger import dag, function, object_type
from dagger.mod import DefaultPath, Ignore

SOURCE_IGNORE = [
    ".git",
    ".venv",
    ".env",
    ".env.*",
    ".kamal/secrets",
    "target",
    "dist",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "**/__pycache__",
]


@object_type
class HeadroomBuilder:
    """Build and smoke-test Headroom from the active checkout."""

    def _build_env(
        self, source: dagger.Directory, python_version: str
    ) -> dagger.Container:
        return (
            dag.container()
            .from_(f"python:{python_version}-bookworm")
            .with_env_variable("CARGO_HOME", "/root/.cargo")
            .with_env_variable("RUSTUP_HOME", "/root/.rustup")
            .with_env_variable(
                "PATH",
                "/root/.cargo/bin:/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            )
            .with_exec(
                [
                    "sh",
                    "-lc",
                    "apt-get update && apt-get install -y --no-install-recommends "
                    "build-essential g++ curl ca-certificates patchelf pkg-config git "
                    "&& rm -rf /var/lib/apt/lists/*",
                ]
            )
            .with_exec(
                [
                    "sh",
                    "-lc",
                    "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs "
                    "| sh -s -- -y --no-modify-path --profile minimal --default-toolchain 1.95.0",
                ]
            )
            .with_exec(
                [
                    "python",
                    "-m",
                    "pip",
                    "install",
                    "--no-cache-dir",
                    "uv==0.11.18",
                    "maturin>=1.5,<2.0",
                ]
            )
            .with_mounted_cache(
                "/root/.cache/uv", dag.cache_volume("headroom-uv-cache")
            )
            .with_mounted_cache(
                "/root/.cargo/registry", dag.cache_volume("headroom-cargo-registry")
            )
            .with_mounted_cache(
                "/work/target", dag.cache_volume("headroom-cargo-target")
            )
            .with_directory("/work", source)
            .with_workdir("/work")
        )

    @function
    def build_wheel(
        self,
        source: Annotated[
            dagger.Directory,
            DefaultPath("."),
            Ignore(SOURCE_IGNORE),
        ],
        python_version: str = "3.11",
        profile: str = "ci",
    ) -> dagger.Directory:
        """Build a Headroom wheel and return the dist directory."""
        return (
            self._build_env(source, python_version)
            .with_exec(
                [
                    "sh",
                    "-lc",
                    f". /root/.cargo/env && maturin build --profile {profile} --out /dist --interpreter python",
                ]
            )
            .directory("/dist")
        )

    @function
    async def smoke_wheel(
        self,
        source: Annotated[
            dagger.Directory,
            DefaultPath("."),
            Ignore(SOURCE_IGNORE),
        ],
        python_version: str = "3.11",
        extras: str = "proxy",
        profile: str = "ci",
    ) -> str:
        """Build the wheel, install it in a clean venv, and run CLI/import smoke checks."""
        return await (
            self._build_env(source, python_version)
            .with_exec(
                [
                    "sh",
                    "-lc",
                    f". /root/.cargo/env && maturin build --profile {profile} --out /dist --interpreter python",
                ]
            )
            .with_exec(["python", "-m", "venv", "/tmp/headroom-smoke"])
            .with_exec(
                [
                    "sh",
                    "-lc",
                    f"wheel=$(find /dist -maxdepth 1 -name '*.whl' | sort | tail -n 1) "
                    f'&& /tmp/headroom-smoke/bin/pip install "$wheel[{extras}]"',
                ]
            )
            .with_exec(
                [
                    "/tmp/headroom-smoke/bin/python",
                    "-c",
                    "from headroom._core import SmartCrusher; print(SmartCrusher.__name__)",
                ]
            )
            .with_exec(["/tmp/headroom-smoke/bin/headroom", "--version"])
            .stdout()
        )

    @function
    def dev_install_script(
        self,
        source: Annotated[
            dagger.Directory,
            DefaultPath("."),
            Ignore(SOURCE_IGNORE),
        ],
        python_version: str = "3.11",
        extras: str = "proxy",
        profile: str = "ci",
    ) -> dagger.Directory:
        """Return a host-side install script plus the freshly built wheel."""
        script = f"""#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
wheel="$(find "$script_dir/dist" -maxdepth 1 -name '*.whl' | sort | tail -n 1)"

if [[ -z "$wheel" ]]; then
  echo "No Headroom wheel found under $script_dir/dist" >&2
  exit 2
fi

uv tool install --force --python {python_version} "$wheel[{extras}]"
uv tool update-shell || true
tool_bin="$(uv tool dir --bin 2>/dev/null || true)"
if [[ -n "$tool_bin" ]]; then
  export PATH="$tool_bin:$PATH"
else
  export PATH="$HOME/.local/bin:$PATH"
fi
headroom --version
"""
        dist = self.build_wheel(source, python_version, profile)
        return (
            dag.directory()
            .with_directory("dist", dist)
            .with_new_file(
                "install-headroom-from-wheel",
                script,
                permissions=0o755,
            )
        )
