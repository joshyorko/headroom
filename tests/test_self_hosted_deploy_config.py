import subprocess
from pathlib import Path


def _render_compose() -> str:
    return subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "compose.override.yml",
            "config",
            "--no-interpolate",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_self_hosted_compose_selects_external_memory_backend() -> None:
    rendered = _render_compose()

    assert "--memory-backend" not in rendered
    assert "--memory-neo4j-uri" not in rendered
    assert "--memory-neo4j-user" not in rendered
    assert "HEADROOM_MEMORY_BACKEND=${HEADROOM_MEMORY_BACKEND:-qdrant-neo4j}" in rendered
    assert "HEADROOM_QDRANT_HOST=${HEADROOM_QDRANT_HOST:-qdrant}" in rendered
    assert "HEADROOM_QDRANT_PORT=${HEADROOM_QDRANT_PORT:-6333}" in rendered
    assert "HEADROOM_NEO4J_URI=${HEADROOM_NEO4J_URI:-neo4j://neo4j:7687}" in rendered
    assert "HEADROOM_NEO4J_USER=${HEADROOM_NEO4J_USER:-neo4j}" in rendered
    assert "HEADROOM_NEO4J_PASSWORD=${HEADROOM_NEO4J_PASSWORD:-devpassword}" in rendered


def test_kamal_proxy_allows_long_running_generation_requests() -> None:
    deploy_config = (Path(__file__).parents[1] / "config" / "deploy.yml").read_text()

    assert "response_timeout: <%= headroom_request_timeout %>" in deploy_config
    assert (
        'HEADROOM_WRITE_TIMEOUT_SECONDS: "<%= headroom_write_timeout_seconds %>"' in deploy_config
    )


def test_kamal_config_removes_unused_effort_settings() -> None:
    deploy_config = (Path(__file__).parents[1] / "config" / "deploy.yml").read_text()

    assert "HEADROOM_EFFORT_ROUTER" not in deploy_config
    assert "HEADROOM_MECHANICAL_EFFORT" not in deploy_config


def test_kamal_proxy_exposes_trusted_dashboard_cidr_settings() -> None:
    deploy_config = (Path(__file__).parents[1] / "config" / "deploy.yml").read_text()

    assert "HEADROOM_PROXY_TRUSTED_GATEWAY_CIDRS:" in deploy_config
    assert "HEADROOM_PROXY_TRUSTED_DASHBOARD_CLIENT_CIDRS:" in deploy_config
