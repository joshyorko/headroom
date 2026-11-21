"""Exercise the same dotenv interpolation Kamal uses for the proxy token."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("legacy_expression", [False, True], ids=["current", "broken-default"])
def test_kamal_proxy_token_matches_the_configured_value(tmp_path, legacy_expression):
    ruby = os.environ.get("KAMAL_TEST_RUBY") or shutil.which("ruby")
    if not ruby:
        if os.environ.get("KAMAL_TEST_REQUIRE_DOTENV") == "1":
            pytest.fail("Ruby is required for the Kamal compatibility check")
        pytest.skip("Ruby is unavailable")
    require_dotenv = (
        'gem "dotenv", ENV["KAMAL_TEST_DOTENV_VERSION"] '
        'if ENV["KAMAL_TEST_DOTENV_VERSION"]; require "dotenv"; '
    )
    probe = subprocess.run([ruby, "-e", require_dotenv + "exit 0"], capture_output=True)
    if probe.returncode:
        if os.environ.get("KAMAL_TEST_REQUIRE_DOTENV") == "1":
            pytest.fail(f"Ruby dotenv is required: {probe.stderr.decode(errors='replace')}")
        pytest.skip("Ruby dotenv is unavailable")

    source = Path(__file__).resolve().parents[1] / ".kamal" / "secrets"
    line = next(
        line for line in source.read_text().splitlines() if line.startswith("HEADROOM_PROXY_TOKEN=")
    )
    if legacy_expression:
        line = "HEADROOM_PROXY_TOKEN=${HEADROOM_PROXY_TOKEN:-}"
    fixture = tmp_path / "secrets"
    fixture.write_text(line + "\n")
    env = {**os.environ, "HEADROOM_PROXY_TOKEN": "synthetic-test-token"}
    # dotenv 2 parses file values directly; dotenv 3 needs overwrite to avoid
    # masking a malformed expression with the existing environment value.
    result = subprocess.run(
        [
            ruby,
            "-e",
            require_dotenv + 'v=Gem.loaded_specs.fetch("dotenv").version; '
            'parsed=v >= Gem::Version.new("3.0") ? '
            "Dotenv.parse(ARGV.fetch(0), overwrite: true) : Dotenv.parse(ARGV.fetch(0)); "
            'puts(parsed["HEADROOM_PROXY_TOKEN"] == ENV["HEADROOM_PROXY_TOKEN"] ? "match" : "mismatch")',
            str(fixture),
        ],
        env=env,
        capture_output=True,
    )
    assert result.returncode == 0, f"Ruby dotenv failed: {result.stderr.decode(errors='replace')}"
    assert result.stdout.decode().strip() == ("mismatch" if legacy_expression else "match")
