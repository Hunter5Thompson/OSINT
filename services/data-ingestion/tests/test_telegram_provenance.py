from __future__ import annotations

from types import SimpleNamespace

from feeds.telegram_collector import build_telegram_payload


def _channel(handle="@Rybar"):
    return SimpleNamespace(handle=handle, source_bias="state", category="mil")


def test_build_telegram_payload_namespaced_provider_and_published():
    payload = build_telegram_payload(
        channel=_channel(), message_id=42, title="msg",
        url="https://t.me/Rybar/42", published="2026-05-31T08:00:00+00:00",
        content_hash="h1", enrichment=None, forwarded_from=None,
        has_media=False, media_paths=[], media_types=[], vision_status="none",
    )
    assert payload["source_type"] == "telegram"
    assert payload["provider"] == "telegram:rybar"          # @ stripped, lowercased
    assert payload["published_at"] == "2026-05-31T08:00:00+00:00"
    assert payload["telegram_message_id"] == 42
    assert "credibility_score" not in payload
