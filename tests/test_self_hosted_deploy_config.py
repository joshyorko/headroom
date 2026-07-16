from pathlib import Path


def test_kamal_proxy_allows_long_running_generation_requests() -> None:
    deploy_config = (Path(__file__).parents[1] / "config" / "deploy.yml").read_text()

    assert "response_timeout: <%= headroom_request_timeout %>" in deploy_config


def test_kamal_proxy_exposes_trusted_dashboard_cidr_settings() -> None:
    deploy_config = (Path(__file__).parents[1] / "config" / "deploy.yml").read_text()

    assert "HEADROOM_PROXY_TRUSTED_GATEWAY_CIDRS:" in deploy_config
    assert "HEADROOM_PROXY_TRUSTED_DASHBOARD_CLIENT_CIDRS:" in deploy_config
