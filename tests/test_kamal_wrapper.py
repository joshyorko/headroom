import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]


def _executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(0o755)


def test_kamal_wrapper_uses_docker_when_mise_shim_is_inactive(tmp_path: Path) -> None:
    tool_dir = tmp_path / "tools"
    tool_dir.mkdir()
    mise_data_dir = tmp_path / "mise"
    mise_shim_dir = mise_data_dir / "shims"
    mise_shim_dir.mkdir(parents=True)
    docker_args = tmp_path / "docker-args"

    _executable(
        mise_shim_dir / "kamal",
        "#!/bin/sh\nexit 97\n",
    )
    _executable(
        tool_dir / "mise",
        '#!/bin/sh\n[ "$1" = "which" ] && exit 1\nexit 0\n',
    )
    _executable(
        tool_dir / "docker",
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$DOCKER_ARGS"\n',
    )

    environment = os.environ.copy()
    environment["MISE_DATA_DIR"] = str(mise_data_dir)
    environment["PATH"] = f"{mise_shim_dir}{os.pathsep}{tool_dir}{os.pathsep}{os.defpath}"
    environment["DOCKER_ARGS"] = str(docker_args)

    subprocess.run(
        [str(REPO_ROOT / "bin" / "kamal"), "version"],
        check=True,
        cwd=REPO_ROOT,
        env=environment,
    )

    assert "ghcr.io/basecamp/kamal:latest" in docker_args.read_text().splitlines()
