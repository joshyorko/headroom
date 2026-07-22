from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "headroom-rebuild-install"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _run_script(
    tmp_path: Path,
    *,
    present: set[str],
    include_brew: bool = True,
    brew_installs: bool = True,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(SCRIPT, scripts / SCRIPT.name)

    fake_bin = tmp_path / "bin"
    templates = tmp_path / "templates"
    fake_bin.mkdir()
    templates.mkdir()
    (fake_bin / "dirname").symlink_to("/usr/bin/dirname")
    (fake_bin / "rm").symlink_to("/usr/bin/rm")

    _write_executable(
        templates / "dagger",
        """#!/usr/bin/bash
printf 'dagger %s\n' "$*" >> "$CALL_LOG"
[[ "$*" == "call dev-install-script export --path dist/headroom-dev" ]] || exit 3
/usr/bin/mkdir -p "$PWD/dist/headroom-dev"
printf '#!/usr/bin/bash\nprintf "install\\n" >> "$CALL_LOG"\n' > "$PWD/dist/headroom-dev/install-headroom-from-wheel"
/usr/bin/chmod +x "$PWD/dist/headroom-dev/install-headroom-from-wheel"
""",
    )
    _write_executable(templates / "uv", "#!/usr/bin/bash\nexit 0\n")

    for command in present:
        shutil.copy2(templates / command, fake_bin / command)

    if include_brew:
        _write_executable(
            fake_bin / "brew",
            """#!/usr/bin/bash
printf 'brew %s\n' "$*" >> "$CALL_LOG"
if [[ "$BREW_INSTALLS" == "1" ]]; then
  /usr/bin/cp "$TEMPLATE_DIR/$2" "$FAKE_BIN/$2"
  /usr/bin/chmod +x "$FAKE_BIN/$2"
fi
""",
        )

    call_log = tmp_path / "calls.log"
    env = {
        **os.environ,
        "PATH": str(fake_bin),
        "CALL_LOG": str(call_log),
        "TEMPLATE_DIR": str(templates),
        "FAKE_BIN": str(fake_bin),
        "BREW_INSTALLS": "1" if brew_installs else "0",
    }
    result = subprocess.run(
        ["/usr/bin/bash", str(scripts / SCRIPT.name)],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    calls = call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []
    return result, calls


def test_existing_tools_skip_homebrew(tmp_path: Path) -> None:
    result, calls = _run_script(tmp_path, present={"dagger", "uv"})

    assert result.returncode == 0, result.stderr
    assert not any(call.startswith("brew ") for call in calls)
    assert calls[-2:] == [
        "dagger call dev-install-script export --path dist/headroom-dev",
        "install",
    ]


def test_missing_dagger_is_installed_with_homebrew(tmp_path: Path) -> None:
    result, calls = _run_script(tmp_path, present={"uv"})

    assert result.returncode == 0, result.stderr
    assert "brew install dagger" in calls
    assert calls[-1] == "install"


def test_missing_uv_is_installed_with_homebrew(tmp_path: Path) -> None:
    result, calls = _run_script(tmp_path, present={"dagger"})

    assert result.returncode == 0, result.stderr
    assert "brew install uv" in calls
    assert calls[-1] == "install"


def test_missing_homebrew_fails_before_build(tmp_path: Path) -> None:
    result, calls = _run_script(
        tmp_path,
        present={"uv"},
        include_brew=False,
    )

    assert result.returncode == 127
    assert "Homebrew is required" in result.stderr
    assert not any(call.startswith("dagger ") for call in calls)


def test_successful_brew_without_command_fails_clearly(tmp_path: Path) -> None:
    result, calls = _run_script(
        tmp_path,
        present={"uv"},
        brew_installs=False,
    )

    assert result.returncode == 127
    assert "dagger is still unavailable on PATH" in result.stderr
    assert calls == ["brew install dagger"]
