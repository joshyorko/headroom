"""Tests for OTEL-backed operational observability."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from headroom.observability import (
    HeadroomOtelMetrics,
    get_otel_meter,
    reset_otel_metrics,
    set_otel_metrics,
)
from headroom.proxy.prometheus_metrics import PrometheusMetrics
from headroom.telemetry.context import MAX_DISTINCT_MODELS
from headroom.transforms.pipeline import TransformPipeline


def _collect_metrics(reader: InMemoryMetricReader) -> dict[str, Any]:
    data = reader.get_metrics_data()
    collected: dict[str, Any] = {}

    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                collected[metric.name] = metric

    return collected


def _find_point(metric: Any, **expected_attributes: Any) -> Any:
    for point in metric.data.data_points:
        if all(point.attributes.get(key) == value for key, value in expected_attributes.items()):
            return point
    raise AssertionError(f"No datapoint matched attributes: {expected_attributes}")


def test_headroom_otel_metrics_records_proxy_and_pipeline_metrics() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    otel_metrics = HeadroomOtelMetrics(meter_provider=provider)

    otel_metrics.record_proxy_request(
        provider="anthropic",
        model="claude-opus-4-6",
        input_tokens=120,
        output_tokens=30,
        tokens_saved=45,
        tool_search_saved=15,
        latency_ms=18.5,
        cached=True,
        overhead_ms=4.0,
        ttfb_ms=12.0,
        cache_read_tokens=25,
        cache_write_tokens=35,
        cache_write_5m_tokens=10,
        cache_write_1h_tokens=25,
        uncached_input_tokens=60,
    )
    otel_metrics.record_proxy_cache_bust(tokens_lost=7)
    otel_metrics.record_pipeline_run(
        model="claude-opus-4-6",
        provider="anthropic",
        tokens_before=120,
        tokens_after=75,
        duration_ms=6.5,
        timing={"_deep_copy": 0.2, "router": 3.5, "pipeline_total": 6.5},
        transforms_applied=["router:smart_crusher:0.35"],
        waste_signals={"json_bloat": 12},
    )

    metrics = _collect_metrics(reader)

    requests = metrics["headroom.proxy.requests"]
    request_point = _find_point(
        requests,
        provider="anthropic",
        model="claude-opus-4-6",
        cached=True,
    )
    assert request_point.value == 1

    saved_tokens = metrics["headroom.proxy.tokens.saved"]
    saved_point = _find_point(
        saved_tokens,
        provider="anthropic",
        model="claude-opus-4-6",
        cached=True,
    )
    assert saved_point.value == 60

    tool_schema_saved = metrics["headroom.proxy.tokens.tool_schema_saved"]
    tool_schema_point = _find_point(
        tool_schema_saved,
        provider="anthropic",
        model="claude-opus-4-6",
        cached=True,
    )
    assert tool_schema_point.value == 15

    compression_saved = metrics["headroom.compression.tokens.saved"]
    compression_saved_point = _find_point(
        compression_saved,
        provider="anthropic",
        model="claude-opus-4-6",
    )
    assert compression_saved_point.value == 45

    latency = metrics["headroom.proxy.request.duration"]
    latency_point = _find_point(
        latency,
        provider="anthropic",
        model="claude-opus-4-6",
        cached=True,
    )
    assert latency_point.count == 1
    assert latency_point.sum == pytest.approx(0.0185)

    ttl_tokens = metrics["headroom.proxy.cache.write_ttl_tokens"]
    five_minute_ttl = _find_point(
        ttl_tokens,
        provider="anthropic",
        model="claude-opus-4-6",
        ttl="5m",
    )
    assert five_minute_ttl.value == 10

    compression_runs = metrics["headroom.compression.runs"]
    compression_point = _find_point(
        compression_runs,
        provider="anthropic",
        model="claude-opus-4-6",
    )
    assert compression_point.value == 1

    stage_duration = metrics["headroom.compression.stage.duration"]
    router_stage = _find_point(
        stage_duration,
        provider="anthropic",
        model="claude-opus-4-6",
        stage="router",
    )
    assert router_stage.count == 1
    assert router_stage.sum == pytest.approx(0.0035)

    assert len(stage_duration.data.data_points) == 1

    waste_tokens = metrics["headroom.compression.waste.tokens"]
    waste_point = _find_point(
        waste_tokens,
        provider="anthropic",
        model="claude-opus-4-6",
        signal="json_bloat",
    )
    assert waste_point.value == 12


def test_get_otel_meter_uses_headrooms_configured_provider() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    set_otel_metrics(HeadroomOtelMetrics(meter_provider=provider))

    try:
        meter = get_otel_meter("example.integration", "1.0.0")
        meter.create_counter("example.integration.events").add(1, {"source": "test"})

        metric = _collect_metrics(reader)["example.integration.events"]
        point = _find_point(metric, source="test")
        assert point.value == 1
    finally:
        reset_otel_metrics()


@dataclass
class _SpyMetrics:
    pipeline_calls: list[dict[str, Any]] = field(default_factory=list)

    def record_pipeline_run(self, **kwargs: Any) -> None:
        self.pipeline_calls.append(kwargs)


@dataclass
class _SpyProxyMetrics:
    failed_calls: list[dict[str, Any]] = field(default_factory=list)
    rate_limited_calls: list[dict[str, Any]] = field(default_factory=list)

    def record_proxy_failed(self, **kwargs: Any) -> None:
        self.failed_calls.append(kwargs)

    def record_proxy_rate_limited(self, **kwargs: Any) -> None:
        self.rate_limited_calls.append(kwargs)


def test_transform_pipeline_simulate_skips_metric_recording() -> None:
    spy = _SpyMetrics()
    set_otel_metrics(spy)  # type: ignore[arg-type]

    try:
        pipeline = TransformPipeline(transforms=[])
        messages = [{"role": "user", "content": "hello world"}]

        pipeline.apply(messages, model="gpt-4o", model_limit=1024)
        assert len(spy.pipeline_calls) == 1

        pipeline.simulate(messages, model="gpt-4o", model_limit=1024)
        assert len(spy.pipeline_calls) == 1
    finally:
        reset_otel_metrics()


def test_proxy_failure_and_rate_limit_metrics_include_provider_labels() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    otel_metrics = HeadroomOtelMetrics(meter_provider=provider)

    otel_metrics.record_proxy_failed(provider="openai")
    otel_metrics.record_proxy_rate_limited(provider="anthropic", model="claude-sonnet")

    metrics = _collect_metrics(reader)

    failed_point = _find_point(metrics["headroom.proxy.requests.failed"], provider="openai")
    assert failed_point.value == 1

    rate_limited_point = _find_point(
        metrics["headroom.proxy.requests.rate_limited"],
        provider="anthropic",
        model="claude-sonnet",
    )
    assert rate_limited_point.value == 1


@pytest.mark.asyncio
async def test_prometheus_metrics_reads_late_configured_otel_metrics() -> None:
    spy = _SpyProxyMetrics()
    metrics = PrometheusMetrics()
    set_otel_metrics(spy)  # type: ignore[arg-type]

    try:
        await metrics.record_failed(provider="openai")
        await metrics.record_rate_limited(provider="anthropic", model="claude-sonnet")

        assert spy.failed_calls == [{"provider": "openai", "model": None}]
        assert spy.rate_limited_calls == [{"provider": "anthropic", "model": "claude-sonnet"}]
    finally:
        reset_otel_metrics()


@pytest.mark.asyncio
async def test_prometheus_metrics_clamps_negative_token_savings() -> None:
    metrics = PrometheusMetrics()

    await metrics.record_request(
        provider="openai",
        model="openai-compatible",
        input_tokens=100,
        output_tokens=5,
        tokens_saved=-25,
        latency_ms=1.0,
    )

    assert metrics.tokens_saved_total == 0
    assert metrics.savings_history[-1][1] == 0


@pytest.mark.asyncio
async def test_prometheus_metrics_caps_model_cardinality() -> None:
    """A client sending unbounded distinct models cannot grow the per-model dicts
    past MAX_DISTINCT_MODELS + the "other" sentinel, while accounting stays exact."""
    metrics = PrometheusMetrics(stateless=True)

    async def record(model: str) -> None:
        await metrics.record_request(
            provider="anthropic",
            model=model,
            input_tokens=10,
            output_tokens=1,
            tokens_saved=1,
            latency_ms=1.0,
            cache_read_tokens=1,  # enter the prefix-cache block -> _cache_requests_by_model
        )

    # Fill exactly to the cap with distinct models: no bucketing yet.
    for i in range(MAX_DISTINCT_MODELS):
        await record(f"model_{i}")
    assert len(metrics.requests_by_model) == MAX_DISTINCT_MODELS
    assert len(metrics._cache_requests_by_model) == MAX_DISTINCT_MODELS
    assert "other" not in metrics.requests_by_model

    # New distinct models past the cap bucket into "other", never their own key.
    for i in range(5):
        await record(f"overflow_{i}")
    assert "overflow_0" not in metrics.requests_by_model
    assert metrics.requests_by_model["other"] == 5
    assert metrics._cache_requests_by_model["other"] == 5
    assert len(metrics.requests_by_model) == MAX_DISTINCT_MODELS + 1
    assert len(metrics._cache_requests_by_model) == MAX_DISTINCT_MODELS + 1

    # An already-tracked model keeps incrementing after the cap is reached.
    await record("model_0")
    assert metrics.requests_by_model["model_0"] == 2

    # Accounting is preserved: every request is counted somewhere.
    total_calls = MAX_DISTINCT_MODELS + 5 + 1
    assert metrics.requests_total == total_calls
    assert sum(metrics.requests_by_model.values()) == total_calls


@pytest.mark.asyncio
async def test_prometheus_metrics_model_cardinality_warns_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Bucketing into "other" logs exactly one warning, not one per request."""
    metrics = PrometheusMetrics(stateless=True)
    with caplog.at_level(logging.WARNING, logger="headroom.proxy"):
        for i in range(MAX_DISTINCT_MODELS + 10):
            await metrics.record_request(
                provider="openai",
                model=f"model_{i}",
                input_tokens=10,
                output_tokens=1,
                tokens_saved=1,
                latency_ms=1.0,
            )
    cap_warnings = [r for r in caplog.records if "cardinality cap" in r.getMessage()]
    assert len(cap_warnings) == 1


@pytest.mark.asyncio
async def test_prometheus_metrics_reset_rearms_cardinality_warning() -> None:
    """reset_runtime clears the model dicts and re-arms the one-shot cap warning."""
    metrics = PrometheusMetrics(stateless=True)
    for i in range(MAX_DISTINCT_MODELS + 5):
        await metrics.record_request(
            provider="openai",
            model=f"model_{i}",
            input_tokens=1,
            output_tokens=1,
            tokens_saved=1,
            latency_ms=1.0,
            cache_read_tokens=1,
        )
    assert metrics._model_cardinality_warned is True

    await metrics.reset_runtime()

    assert metrics._model_cardinality_warned is False
    assert len(metrics.requests_by_model) == 0
    assert len(metrics._cache_requests_by_model) == 0


@pytest.mark.asyncio
async def test_prometheus_metrics_export_bounds_model_series() -> None:
    """export() emits at most MAX_DISTINCT_MODELS model series plus the 'other' bucket."""
    metrics = PrometheusMetrics(stateless=True)
    for i in range(MAX_DISTINCT_MODELS + 20):
        await metrics.record_request(
            provider="openai",
            model=f"model_{i}",
            input_tokens=1,
            output_tokens=1,
            tokens_saved=1,
            latency_ms=1.0,
        )
    text = await metrics.export()
    series = text.count("headroom_requests_by_model{")
    assert series <= MAX_DISTINCT_MODELS + 1
    assert 'headroom_requests_by_model{model="other"}' in text
