"""Regression checks for Docker Compose persistence wiring."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_top_level_compose_pins_headroom_state_to_named_volume() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "- headroom_workspace:/home/nonroot/.headroom" in compose
    assert "- HOME=/home/nonroot" in compose
    assert "- HEADROOM_WORKSPACE_DIR=/home/nonroot/.headroom" in compose
    assert "- HEADROOM_CONFIG_DIR=/home/nonroot/.headroom/config" in compose
