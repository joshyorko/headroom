"""Browser credentials unlock the dashboard, never the provider relay."""

import base64
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from headroom.proxy.server import ProxyConfig, create_app

TOKEN = "dashboard-test-token"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("HEADROOM_SKIP_UPSTREAM_CHECK", "1")
    app = create_app(
        ProxyConfig(
            proxy_token=TOKEN,
            optimize=False,
            cache_enabled=False,
            rate_limit_enabled=False,
            cost_tracking_enabled=False,
        )
    )
    app.state.observed_authorizations = []

    @app.middleware("http")
    async def observe(request, call_next):
        response = await call_next(request)
        app.state.observed_authorizations.append(
            dict(request.scope["headers"]).get(b"authorization")
        )
        return response

    with TestClient(app, base_url="http://10.10.10.89", client=("192.0.2.5", 1234)) as c:
        yield c


@pytest.mark.parametrize("path", ["/dashboard", "/dashboard/", "/stats", "/stats-history"])
def test_browser_receives_sign_in_challenge(client, path):
    response = client.get(path)
    assert response.status_code == 401
    assert (
        response.headers["www-authenticate"] == 'Basic realm="Headroom dashboard", charset="UTF-8"'
    )


@pytest.mark.parametrize(
    "path",
    [
        "/dashboard",
        "/dashboard/",
        "/dashboard/static/alpine.min.js",
        "/stats",
        "/stats-history",
        "/stats-lifetime",
        "/subscription-window",
        "/quota",
    ],
)
def test_browser_credentials_load_dashboard_and_data(client, path):
    response = client.get(path, auth=("headroom", TOKEN))
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/v1/responses"),
        ("GET", "/admin/upstream"),
        ("POST", "/dashboard"),
        ("GET", "/dashboard/unknown"),
        ("HEAD", "/stats"),
        ("POST", "/stats"),
        ("GET", "/stats-lifetime/export"),
    ],
)
def test_browser_credentials_do_not_authorize_other_routes(client, method, path):
    with patch.object(client.app.state.proxy, "handle_passthrough", new=AsyncMock()) as relay:
        response = client.request(method, path, auth=("headroom", TOKEN))
    assert response.status_code == 401
    assert "www-authenticate" not in response.headers
    relay.assert_not_called()


@pytest.mark.parametrize(
    "authorization",
    [
        "Basic ???",
        "Basic " + base64.b64encode(b"headroom").decode(),
        "Basic " + base64.b64encode(b"other:" + TOKEN.encode()).decode(),
        "Basic " + base64.b64encode(b"headroom:wrong").decode(),
        "Basic " + base64.b64encode(b"headroom:\xff").decode(),
    ],
)
def test_invalid_browser_credentials_are_rejected(client, authorization):
    assert client.get("/dashboard", headers={"Authorization": authorization}).status_code == 401


@pytest.mark.parametrize("token", ["wrong", ""])
def test_explicit_invalid_token_cannot_fall_back_to_browser_credentials(client, token):
    response = client.get(
        "/dashboard", auth=("headroom", TOKEN), headers={"X-Headroom-Proxy-Token": token}
    )
    assert response.status_code == 401


def test_browser_credential_is_removed_before_handler(client):
    assert client.get("/stats-history", auth=("headroom", TOKEN)).status_code == 200
    assert client.app.state.observed_authorizations[-1] is None


@pytest.mark.parametrize("method,path", [("GET", "/settings/schema"), ("POST", "/settings")])
def test_browser_sign_in_preserves_settings_network_and_origin_guards(client, method, path):
    response = client.request(
        method, path, auth=("headroom", TOKEN), headers={"Origin": "http://untrusted.example"}
    )
    assert response.status_code in {403, 404}


def test_token_in_query_string_does_not_sign_in(client):
    assert client.get("/dashboard?token=" + TOKEN).status_code == 401
