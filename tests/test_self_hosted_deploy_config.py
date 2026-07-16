from pathlib import Path


def test_kamal_proxy_allows_long_running_generation_requests() -> None:
    deploy_config = (Path(__file__).parents[1] / "config" / "deploy.yml").read_text()

    assert "response_timeout: <%= headroom_request_timeout %>" in deploy_config
