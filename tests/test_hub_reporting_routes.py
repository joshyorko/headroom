"""Exercise the same authenticated management requests T3 uses for hub usage."""

import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from headroom.proxy import server
from headroom.proxy.models import ProxyConfig
from headroom.subscription.base import QuotaTrackerRegistry
from headroom.subscription.codex_rate_limits import CodexRateLimitState
from headroom.subscription.models import SubscriptionSnapshot
from headroom.subscription.tracker import SubscriptionTracker

TOKEN = "test-hub-operator-token"
MANAGEMENT = "/v0/management"
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


@pytest.fixture
def hub(monkeypatch):
    registry = QuotaTrackerRegistry()
    tracker = CodexRateLimitState()
    tracker.update_from_headers(
        {
            "x-codex-primary-used-percent": "37.5",
            "x-codex-primary-window-minutes": "300",
            "x-codex-primary-reset-at": str(int(time.time()) + 3600),
        }
    )
    registry.register(tracker)
    monkeypatch.setattr(server, "get_quota_registry", lambda: registry)
    app = server.create_app(
        ProxyConfig(
            proxy_token=TOKEN,
            optimize=False,
            cache_enabled=False,
            rate_limit_enabled=False,
            cost_tracking_enabled=False,
            stateless=True,
        )
    )
    relay = AsyncMock(return_value=JSONResponse({"unexpected": "upstream"}, status_code=418))
    monkeypatch.setattr(app.state.proxy, "handle_passthrough", relay)
    client = TestClient(app, base_url="http://10.10.10.89", client=("192.0.2.5", 1234))
    client.headers["Authorization"] = f"Bearer {TOKEN}"
    yield client, relay, registry
    client.close()


def test_t3_lists_accounts_then_reads_codex_usage(hub):
    client, relay, _ = hub
    listing = client.get(f"{MANAGEMENT}/auth-files")
    assert listing.status_code == 200
    account = listing.json()["files"][0]
    assert account["provider"] == "codex"
    assert account["disabled"] is False
    assert account["id"] == account["auth_index"] == "headroom-codex"
    response = client.post(
        f"{MANAGEMENT}/api-call",
        json={
            "auth_index": account["auth_index"],
            "method": "GET",
            "url": USAGE_URL,
            "header": {"Authorization": "Bearer $TOKEN$"},
        },
    )
    assert response.status_code == 200
    envelope = response.json()
    assert envelope["status_code"] == 200
    payload = json.loads(envelope["body"])
    window = payload["rate_limit"]["primary_window"]
    assert window["used_percent"] == 37.5
    assert window["limit_window_seconds"] == 18000
    assert TOKEN not in response.text + listing.text
    relay.assert_not_awaited()


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic aGVhZHJvb206d3Jvbmc="])
@pytest.mark.parametrize("path", ["auth-files", "api-call"])
def test_remote_hub_requires_valid_proxy_credential(hub, authorization, path):
    client, relay, _ = hub
    client.headers.pop("Authorization")
    headers = {} if authorization is None else {"Authorization": authorization}
    response = client.request(
        "GET" if path == "auth-files" else "POST", f"{MANAGEMENT}/{path}", headers=headers
    )
    assert response.status_code == 401
    relay.assert_not_awaited()


def test_explicit_proxy_header_can_authorize_hub(hub):
    client, relay, _ = hub
    client.headers.pop("Authorization")
    response = client.get(f"{MANAGEMENT}/auth-files", headers={"X-Headroom-Proxy-Token": TOKEN})
    assert response.status_code == 200
    relay.assert_not_awaited()


def test_claude_report_uses_real_subscription_snapshot_without_token_prefix(hub, tmp_path):
    client, relay, registry = hub
    reset = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    tracker = SubscriptionTracker(persist_path=tmp_path / "subscription.json")
    tracker._state.latest = SubscriptionSnapshot.from_api_response(
        {"five_hour": {"utilization": 42.5, "resets_at": reset}},
        token="private-provider-token",
    )
    registry.register(tracker)
    listing = client.get(f"{MANAGEMENT}/auth-files").json()
    assert {account["provider"] for account in listing["files"]} == {"codex", "claude"}
    response = client.post(
        f"{MANAGEMENT}/api-call",
        json={
            "auth_index": "headroom-claude",
            "method": "GET",
            "url": "https://api.anthropic.com/api/oauth/usage",
        },
    )
    envelope = response.json()
    assert envelope["status_code"] == 200
    assert json.loads(envelope["body"])["five_hour"]["utilization"] == 42.5
    assert "private-" not in response.text
    relay.assert_not_awaited()


def test_real_startup_registers_trackers_for_the_hub(monkeypatch):
    monkeypatch.setenv("HEADROOM_SKIP_UPSTREAM_CHECK", "1")
    monkeypatch.setattr("headroom.subscription.tracker._tracker_instance", None)
    app = server.create_app(
        ProxyConfig(
            proxy_token=TOKEN,
            optimize=False,
            cache_enabled=False,
            rate_limit_enabled=False,
            cost_tracking_enabled=False,
            subscription_tracking_enabled=False,
            stateless=True,
        )
    )
    with TestClient(app, base_url="http://10.10.10.89", client=("192.0.2.5", 1234)) as client:
        response = client.get(
            f"{MANAGEMENT}/auth-files", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        assert response.status_code == 200
        assert [account["provider"] for account in response.json()["files"]] == ["codex"]


@pytest.mark.parametrize(
    "body", [None, [], {}, {"auth_index": 123, "method": "GET", "url": USAGE_URL}]
)
def test_malformed_api_call_is_rejected_locally(hub, body):
    client, relay, _ = hub
    response = client.post(f"{MANAGEMENT}/api-call", json=body)
    assert response.status_code == 400
    relay.assert_not_awaited()


@pytest.mark.parametrize(
    "method,path", [("POST", "reset-quota"), ("DELETE", "auth-files"), ("GET", "unknown")]
)
def test_unsupported_management_operations_never_relay(hub, method, path):
    client, relay, _ = hub
    response = client.request(method, f"{MANAGEMENT}/{path}")
    assert response.status_code in {404, 405}
    relay.assert_not_awaited()


@pytest.mark.parametrize(
    "method,url",
    [
        ("GET", "http://169.254.169.254/latest/meta-data/"),
        ("POST", USAGE_URL),
        ("GET", USAGE_URL + "?secret=value"),
    ],
)
def test_api_call_never_fetches_supplied_urls_or_changes_provider_state(hub, method, url):
    client, relay, _ = hub
    response = client.post(
        f"{MANAGEMENT}/api-call",
        json={"auth_index": "headroom-codex", "method": method, "url": url},
    )
    assert response.status_code == 200
    assert response.json()["status_code"] in {403, 405}
    relay.assert_not_awaited()


def test_missing_usage_is_unavailable_instead_of_zero(hub):
    client, relay, registry = hub
    registry.get("codex_rate_limits")._latest = None
    response = client.post(
        f"{MANAGEMENT}/api-call",
        json={"auth_index": "headroom-codex", "method": "GET", "url": USAGE_URL},
    )
    assert response.status_code == 200
    assert response.json()["status_code"] == 503
    relay.assert_not_awaited()


def test_hub_reads_preserve_browser_origin_gate(hub):
    client, relay, _ = hub
    response = client.get(
        f"{MANAGEMENT}/auth-files", headers={"Origin": "https://untrusted.example"}
    )
    assert response.status_code == 403
    relay.assert_not_awaited()
