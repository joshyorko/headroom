"""Exercise the same dotenv interpolation Kamal uses for the proxy token."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_kamal_proxy_token_matches_the_configured_value(tmp_path):
    ruby = os.environ.get("KAMAL_TEST_RUBY") or shutil.which("ruby")
    if not ruby:
        pytest.skip("Ruby is unavailable")
    probe = subprocess.run([ruby, "-r", "dotenv", "-e", "exit 0"], capture_output=True)
    if probe.returncode:
        pytest.skip("Ruby dotenv is unavailable")

    source = Path(__file__).resolve().parents[1] / ".kamal" / "secrets"
    line = next(
        line for line in source.read_text().splitlines() if line.startswith("HEADROOM_PROXY_TOKEN=")
    )
    fixture = tmp_path / "secrets"
    fixture.write_text(line + "\n")
    env = {**os.environ, "HEADROOM_PROXY_TOKEN": "synthetic-test-token"}
    result = subprocess.run(
        [
            ruby,
            "-r",
            "dotenv",
            "-e",
            'v=Dotenv.parse(ARGV.fetch(0), overwrite: true)["HEADROOM_PROXY_TOKEN"]; exit(v == ENV["HEADROOM_PROXY_TOKEN"] ? 0 : 1)',
            str(fixture),
        ],
        env=env,
        capture_output=True,
    )
    assert result.returncode == 0, "Kamal dotenv changed the configured proxy token"
