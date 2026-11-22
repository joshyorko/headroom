import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]


def _executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(0o755)


@pytest.mark.parametrize(
    "docker_host,docker_context,context_host,expected_socket",
    [
        (None, None, "unix:///var/run/docker.sock", "/var/run/docker.sock"),
        (None, None, "unix:///run/user/1000/docker.sock", "/run/user/1000/docker.sock"),
        ("unix:///custom/docker.sock", None, "unused", "/custom/docker.sock"),
        (
            "unix:///custom/docker.sock",
            "rootless",
            "unix:///run/user/1000/docker.sock",
            "/run/user/1000/docker.sock",
        ),
    ],
)
def test_kamal_wrapper_uses_active_docker_socket_when_mise_shim_is_inactive(
    tmp_path: Path,
    docker_host: str | None,
    docker_context: str | None,
    context_host: str,
    expected_socket: str,
) -> None:
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
        "#!/bin/sh\n"
        'if [ "$1" = context ]; then printf \'%s\\n\' "$CONTEXT_HOST"; exit 0; fi\n'
        'printf \'%s\\n\' "$@" > "$DOCKER_ARGS"\n',
    )

    environment = os.environ.copy()
    environment["MISE_DATA_DIR"] = str(mise_data_dir)
    environment["PATH"] = f"{mise_shim_dir}{os.pathsep}{tool_dir}{os.pathsep}{os.defpath}"
    environment["DOCKER_ARGS"] = str(docker_args)
    environment["CONTEXT_HOST"] = context_host
    for name, value in (("DOCKER_HOST", docker_host), ("DOCKER_CONTEXT", docker_context)):
        if value is None:
            environment.pop(name, None)
        else:
            environment[name] = value

    subprocess.run(
        [str(REPO_ROOT / "bin" / "kamal"), "version"],
        check=True,
        cwd=REPO_ROOT,
        env=environment,
    )

    arguments = docker_args.read_text().splitlines()
    assert "ghcr.io/basecamp/kamal:latest" in arguments
    assert f"{expected_socket}:/var/run/docker.sock" in arguments
