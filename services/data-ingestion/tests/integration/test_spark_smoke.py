"""Integration smoke test against real Spark vLLM.

Skipped automatically if Spark is unreachable.
Run explicitly: uv run pytest tests/integration -v

The reachability pre-check honours the ``SPARK_VLLM_URL_OVERRIDE`` environment
variable — point it at an unreachable host (e.g. ``http://127.0.0.1:1``) to
exercise the skip path without touching real config.
"""

from __future__ import annotations

import os

import httpx
import pytest

from config import Settings


def _effective_url() -> str:
    """Resolve the Spark vLLM base URL honouring the override env var."""
    override = os.environ.get("SPARK_VLLM_URL_OVERRIDE")
    if override:
        return override
    return Settings(_env_file=None).ingestion_vllm_url


@pytest.fixture(scope="module")
def spark_base_url() -> str:
    """Verify Spark vLLM is reachable; skip the module if not.

    Issues a short-timeout GET /v1/models. Any connection, timeout, or non-2xx
    response is treated as 'unreachable' and skips the whole module so the
    test suite stays green in environments without access to Spark.
    """
    base_url = _effective_url()
    try:
        resp = httpx.get(f"{base_url}/v1/models", timeout=3.0)
        resp.raise_for_status()
    except (httpx.HTTPError, OSError) as exc:
        pytest.skip(f"spark unreachable: {exc}")
    return base_url


@pytest.fixture(scope="module")
def spark_settings(spark_base_url: str) -> Settings:
    """Settings pinned to the effective Spark URL (respects override)."""
    s = Settings(_env_file=None)
    # Honour the override so _call_vllm dials the same host that the
    # reachability check already confirmed.
    s.ingestion_vllm_url = spark_base_url
    return s


async def test_models_endpoint_lists_expected_model(spark_settings: Settings) -> None:
    """Sanity: /v1/models must advertise the configured ingestion model."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{spark_settings.ingestion_vllm_url}/v1/models")
    assert resp.status_code == 200
    ids = [m["id"] for m in resp.json()["data"]]
    assert spark_settings.ingestion_vllm_model in ids, (
        f"expected {spark_settings.ingestion_vllm_model} in {ids}"
    )


async def test_real_extraction_call(spark_settings: Settings) -> None:
    """Drive a real ``_call_vllm`` against Spark; assert tight schema shape.

    Uses a NATO-flavoured test headline. The pipeline's ``_RESPONSE_SCHEMA``
    enforces ``additionalProperties: false`` + ``required: [title, summary,
    codebook_type, ...]`` so the decoder cannot emit the legacy ``description``
    field that Qwen3.6 used to drift to (regression guard).
    """
    from pipeline import _call_vllm

    result = await _call_vllm(
        title="Test: German air defense intercepts unknown drone over Baltic",
        text=(
            "German air defense confirmed interception of an unknown drone "
            "over the Baltic Sea today. The incident occurred near Rostock "
            "and no casualties were reported."
        ),
        url="http://example.com/test",
        settings=spark_settings,
    )

    # Top-level shape
    assert isinstance(result, dict), f"expected dict, got {type(result)!r}"
    assert "events" in result
    assert "entities" in result
    assert "locations" in result
    assert isinstance(result["events"], list)
    assert isinstance(result["entities"], list)
    assert isinstance(result["locations"], list)

    # Event shape — schema guarantees these required fields.
    assert result["events"], "expected at least one extracted event"
    for event in result["events"]:
        assert "title" in event, f"event missing title: {event!r}"
        assert "summary" in event, f"event missing summary: {event!r}"
        assert "codebook_type" in event, f"event missing codebook_type: {event!r}"
        # Regression guard: Qwen3.6 used to drift 'description' instead of
        # 'summary'. additionalProperties:false in the schema must forbid it.
        assert "description" not in event, (
            f"regression: 'description' field leaked past schema: {event!r}"
        )
