"""Provider model metadata route helpers."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, cast

from fastapi import Request
from fastapi.responses import Response

from headroom.providers.codex.model_metadata import handle_chatgpt_model_metadata
from headroom.proxy.auth_mode import classify_client

logger = logging.getLogger("headroom.providers.model_metadata")

_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_OPENROUTER_MODEL_PREFIX = "openrouter/"


@dataclass(frozen=True, slots=True)
class ModelMetadataEndpoint:
    """OpenAI-compatible model metadata endpoint shape."""

    route_path: str
    upstream_path: str
    passthrough_sub_path: str = "models"


MODEL_METADATA_LIST_ENDPOINT = ModelMetadataEndpoint("/v1/models", "/backend-api/models")


def model_metadata_get_endpoint(model_id: str) -> ModelMetadataEndpoint:
    """Return the single-model metadata endpoint for ``model_id``."""
    return ModelMetadataEndpoint(
        "/v1/models/{model_id}",
        f"/backend-api/models/{model_id}",
    )


def _openrouter_prefixed_model_id(model_id: str) -> str:
    normalized = model_id.strip()
    if normalized.startswith(_OPENROUTER_MODEL_PREFIX):
        return normalized
    return f"{_OPENROUTER_MODEL_PREFIX}{normalized}"


def _openrouter_model_response_entry(upstream_entry: dict[str, Any]) -> dict[str, Any] | None:
    raw_model_id = upstream_entry.get("id")
    if not isinstance(raw_model_id, str) or not raw_model_id.strip():
        return None
    entry = dict(upstream_entry)
    entry["id"] = _openrouter_prefixed_model_id(raw_model_id)
    if not isinstance(entry.get("object"), str) or not entry["object"]:
        entry["object"] = "model"
    if not isinstance(entry.get("created"), int):
        entry["created"] = 0
    if not isinstance(entry.get("owned_by"), str) or not entry["owned_by"]:
        entry["owned_by"] = "openrouter"
    return entry


def _openrouter_models_response_entries(payload: Any) -> tuple[dict[str, Any], ...]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return ()
    return tuple(
        entry
        for raw_entry in data
        if isinstance(raw_entry, dict)
        for entry in (_openrouter_model_response_entry(raw_entry),)
        if entry is not None
    )


def _openrouter_catalog_headers() -> dict[str, str]:
    headers = {"accept": "application/json"}
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    return headers


def _openrouter_error_response(
    message: str,
    *,
    status_code: int = 502,
    code: str = "openrouter_catalog_error",
) -> Response:
    return Response(
        content=json.dumps(
            {
                "error": {
                    "message": message,
                    "type": "server_error",
                    "code": code,
                }
            }
        ),
        status_code=status_code,
        headers={"content-type": "application/json"},
    )


async def _fetch_openrouter_model_entries(proxy: Any) -> tuple[dict[str, Any], ...] | Response:
    try:
        assert proxy.http_client is not None
        response = await proxy.http_client.get(
            _OPENROUTER_MODELS_URL,
            headers=_openrouter_catalog_headers(),
            timeout=15.0,
        )
    except Exception as exc:
        logger.exception("OpenRouter model catalog fetch failed")
        return _openrouter_error_response(f"OpenRouter model catalog fetch failed: {exc}")

    if response.status_code >= 400:
        logger.warning(
            "OpenRouter model catalog fetch failed: HTTP %s: %s",
            response.status_code,
            response.text[:300],
        )
        return _openrouter_error_response(
            f"OpenRouter model catalog fetch failed with HTTP {response.status_code}",
        )

    try:
        payload = response.json()
    except ValueError:
        logger.warning("OpenRouter model catalog response was not valid JSON")
        return _openrouter_error_response("OpenRouter model catalog response was not valid JSON")

    entries = _openrouter_models_response_entries(payload)
    if not entries:
        logger.warning("OpenRouter model catalog response did not contain data[] model ids")
        return _openrouter_error_response("OpenRouter model catalog returned no model ids")
    return entries


async def _handle_openrouter_model_metadata(
    proxy: Any,
    request: Request,
    model_id: str | None,
) -> Response | None:
    if classify_client(request.headers) != "hermes":
        return None

    entries_or_response = await _fetch_openrouter_model_entries(proxy)
    if isinstance(entries_or_response, Response):
        return entries_or_response

    entries = entries_or_response
    if model_id is None:
        return Response(
            content=json.dumps({"object": "list", "data": list(entries)}),
            status_code=200,
            headers={"content-type": "application/json"},
        )

    prefixed_model_id = _openrouter_prefixed_model_id(model_id)
    for entry in entries:
        if entry.get("id") == prefixed_model_id:
            return Response(
                content=json.dumps(entry),
                status_code=200,
                headers={"content-type": "application/json"},
            )

    return Response(
        content=json.dumps(
            {
                "error": {
                    "message": f"Model {prefixed_model_id!r} not found in OpenRouter catalog",
                    "type": "invalid_request_error",
                    "code": "model_not_found",
                }
            }
        ),
        status_code=404,
        headers={"content-type": "application/json"},
    )


async def handle_model_metadata_endpoint(
    proxy: Any,
    request: Request,
    *,
    endpoint: ModelMetadataEndpoint,
    provider_api_base_url: str,
    provider_name: str,
    model_id: str | None = None,
) -> Response:
    """Handle OpenAI-compatible model metadata with Codex ChatGPT-auth support."""
    assert proxy.http_client is not None
    openrouter_response = await _handle_openrouter_model_metadata(proxy, request, model_id)
    if openrouter_response is not None:
        return openrouter_response

    chatgpt_response = await handle_chatgpt_model_metadata(
        proxy.http_client,
        request,
        endpoint.upstream_path,
    )
    if chatgpt_response is not None:
        return chatgpt_response

    return cast(
        Response,
        await proxy.handle_passthrough(
            request,
            provider_api_base_url,
            endpoint.passthrough_sub_path,
            provider_name,
        ),
    )
