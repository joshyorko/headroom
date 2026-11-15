"""An explicitly pinned operator can refresh quota through a remote proxy."""

import asyncio
import base64
import json
import time

import httpx
import pytest

from headroom.subscription import codex_rate_limits as quota
from headroom.subscription.credential_policy import codex_operator_fingerprint


def operator_headers(*, subject="operator", account="workspace", expires=None):
    payload = {
        "iss": "https://auth.openai.com",
        "sub": subject,
        "exp": expires or time.time() + 3600,
        "https://api.openai.com/auth": {"chatgpt_account_id": account},
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return {"Authorization": f"Bearer header.{encoded}.signature", "ChatGPT-Account-Id": account}


@pytest.fixture
def operator(monkeypatch):
    headers = operator_headers()
    monkeypatch.setenv("HEADROOM_CODEX_QUOTA_OPERATOR", codex_operator_fingerprint(headers))
    state = quota.CodexRateLimitState()
    monkeypatch.setattr(quota, "_state", state)
    return headers, state


def test_identity_survives_token_rotation_but_binds_user_and_workspace():
    headers = operator_headers()
    fingerprint = codex_operator_fingerprint(headers)
    assert fingerprint and len(fingerprint) == 64
    assert fingerprint == codex_operator_fingerprint(operator_headers(expires=time.time() + 7200))
    assert fingerprint != codex_operator_fingerprint(operator_headers(subject="someone-else"))
    assert fingerprint != codex_operator_fingerprint(operator_headers(account="another-workspace"))


@pytest.mark.asyncio
async def test_remote_operator_fetches_real_provider_shape(operator, monkeypatch):
    headers, state = operator
    requests = []
    original_client = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 37.5,
                        "limit_window_seconds": 18000,
                        "reset_at": int(time.time()) + 3600,
                    }
                }
            },
        )

    monkeypatch.setattr(
        quota.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(respond)),
    )
    assert quota.maybe_schedule_usage_poll(headers, from_local_operator=False)
    while state._poll_inflight:
        await asyncio.sleep(0)
    assert len(requests) == 1
    assert str(requests[0].url) == quota.CODEX_USAGE_URL
    assert requests[0].headers["authorization"] == headers["Authorization"]
    assert state.get_stats()["primary"]["used_percent"] == 37.5
    assert state.operator_headers()["Authorization"] == headers["Authorization"]
    assert headers["Authorization"] not in json.dumps(state.get_stats())


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["user", "workspace", "header", "expired", "not-jwt"])
async def test_other_credentials_cannot_drive_operator_poll(operator, change):
    headers, state = operator
    if change == "user":
        headers = operator_headers(subject="someone-else")
    elif change == "workspace":
        headers = operator_headers(account="another-workspace")
    elif change == "header":
        headers = {**headers, "ChatGPT-Account-Id": "another-workspace"}
    elif change == "expired":
        headers = operator_headers(expires=time.time() - 10)
    else:
        headers = {**headers, "Authorization": "Bearer arbitrary-api-key"}
    assert not quota.maybe_schedule_usage_poll(headers, from_local_operator=False)
    assert not quota.maybe_schedule_usage_poll(headers, from_local_operator=True)
    assert state.latest is None
    assert not state._poll_inflight


@pytest.mark.asyncio
async def test_on_demand_refresh_uses_only_remembered_operator_and_is_throttled(
    operator, monkeypatch
):
    headers, state = operator
    fetched = []

    async def fetch(url, outgoing):
        fetched.append(outgoing)
        state.remember_operator_headers(outgoing)
        state._end_poll()

    monkeypatch.setattr(quota, "_fetch_and_store_usage", fetch)
    assert quota.maybe_schedule_usage_poll(headers)
    await asyncio.sleep(0)
    assert not await quota.refresh_operator_usage()
    state._last_poll_monotonic = 0
    assert await quota.refresh_operator_usage()
    assert len(fetched) == 2
    monkeypatch.delenv("HEADROOM_CODEX_QUOTA_OPERATOR")
    state._last_poll_monotonic = 0
    assert not await quota.refresh_operator_usage()
    assert len(fetched) == 2


@pytest.mark.asyncio
async def test_cold_hub_without_operator_session_cannot_invent_credentials(operator):
    _, state = operator
    assert not await quota.refresh_operator_usage()
    assert state.latest is None


@pytest.mark.asyncio
async def test_default_collection_keeps_existing_header_snapshot(monkeypatch):
    monkeypatch.delenv("HEADROOM_CODEX_QUOTA_OPERATOR", raising=False)
    state = quota.CodexRateLimitState()
    monkeypatch.setattr(quota, "_state", state)
    state.update_from_headers({"x-codex-primary-used-percent": "25"})
    assert not await quota.refresh_operator_usage()
    assert state.latest.primary.used_percent == 25


def test_other_traffic_headers_cannot_overwrite_pinned_operator(operator):
    _, state = operator
    state.update_from_usage_payload({"rate_limit": {"primary_window": {"used_percent": 25}}})
    state.update_from_headers({"x-codex-primary-used-percent": "99"})
    assert state.latest.primary.used_percent == 25


@pytest.mark.asyncio
async def test_matching_claims_still_require_provider_authorization(operator, monkeypatch):
    headers, state = operator
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        quota.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(401))
        ),
    )
    assert quota.maybe_schedule_usage_poll(headers)
    while state._poll_inflight:
        await asyncio.sleep(0)
    assert state.latest is None
    assert state.operator_headers() is None


@pytest.mark.asyncio
async def test_rejected_token_cannot_replace_verified_operator_credentials(operator, monkeypatch):
    headers, state = operator
    state.remember_operator_headers(headers)
    invalid = {**headers, "Authorization": headers["Authorization"] + "-forged"}
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        quota.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(401))
        ),
    )
    assert quota.maybe_schedule_usage_poll(invalid)
    while state._poll_inflight:
        await asyncio.sleep(0)
    assert state.operator_headers() == headers


def test_remote_codex_turn_populates_the_hub_without_exposing_credentials(operator, monkeypatch):
    from fastapi.testclient import TestClient

    from headroom.proxy.server import ProxyConfig, create_app

    headers, state = operator
    monkeypatch.setenv("HEADROOM_SKIP_UPSTREAM_CHECK", "1")

    original_client = httpx.AsyncClient

    def respond(request):
        assert request.headers["Authorization"] == headers["Authorization"]
        return httpx.Response(
            200,
            json={
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 55,
                        "reset_at": int(time.time()) + 3600,
                        "limit_window_seconds": 18000,
                    }
                }
            },
        )

    class ProviderClient(original_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(respond)
            super().__init__(*args, **kwargs)

    app = create_app(
        ProxyConfig(
            proxy_token="test-proxy-key",
            optimize=False,
            cache_enabled=False,
            rate_limit_enabled=False,
            cost_tracking_enabled=False,
            subscription_tracking_enabled=False,
            stateless=True,
        )
    )

    async def upstream(*args, **kwargs):
        return httpx.Response(
            200,
            json={
                "id": "resp_operator",
                "object": "response",
                "model": "gpt-5.4",
                "output": [],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    monkeypatch.setattr(app.state.proxy, "_retry_request", upstream)
    with TestClient(app, base_url="http://10.10.10.89", client=("192.0.2.5", 1234)) as client:
        monkeypatch.setattr(quota.httpx, "AsyncClient", ProviderClient)
        result = client.post(
            "/v1/responses",
            headers={
                **headers,
                "X-Headroom-Proxy-Token": "test-proxy-key",
            },
            json={"model": "gpt-5.4", "input": "hello"},
        )
        assert result.status_code == 200
        report = client.post(
            "/v0/management/api-call",
            headers={
                "Authorization": "Bearer test-proxy-key",
            },
            json={"auth_index": "headroom-codex", "method": "GET", "url": quota.CODEX_USAGE_URL},
        )
        assert report.status_code == 200
        assert report.json()["status_code"] == 200
        body = json.loads(report.json()["body"])
        assert body["rate_limit"]["primary_window"]["used_percent"] == 55
        assert headers["Authorization"] not in report.text
