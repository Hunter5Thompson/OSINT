#!/usr/bin/env python3
"""Live smoke for Base ReAct tool-calling and Munin synthesis."""

from __future__ import annotations

import argparse
import sys

import httpx

from config import settings


def _react_tool_call_ok(client: httpx.Client, model: str) -> bool:
    response = client.post(
        "chat/completions",
        json={
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": "Look up X. You MUST call the noop tool to do it.",
                }
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "noop",
                        "description": "look something up",
                        "parameters": {
                            "type": "object",
                            "properties": {"q": {"type": "string"}},
                        },
                    },
                }
            ],
            "tool_choice": "auto",
            "temperature": 0,
            "max_tokens": 128,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    response.raise_for_status()
    message = response.json()["choices"][0]["message"]
    names = [
        call.get("function", {}).get("name")
        for call in (message.get("tool_calls") or [])
        if isinstance(call, dict)
    ]
    if "noop" not in names:
        print(
            f"FAIL: base model {model!r} did not call noop (tool_calls={names})",
            file=sys.stderr,
        )
        return False

    print(f"OK: base model {model!r} still calls tools with LoRA enabled")
    return True


def _munin_answers(client: httpx.Client, model: str) -> bool:
    response = client.post(
        "chat/completions",
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Du bist Munin, ein Intelligence-Report-Synthetisierer.",
                },
                {
                    "role": "user",
                    "content": "Erstelle einen kurzen Lagebericht auf Deutsch zur Testlage.",
                },
            ],
            "max_tokens": 200,
            "temperature": 0.1,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    response.raise_for_status()
    content = (response.json()["choices"][0]["message"].get("content") or "").strip()
    if len(content) < 40:
        print(
            f"FAIL: synthesis model {model!r} returned only {len(content)} characters",
            file=sys.stderr,
        )
        return False

    print(f"OK: synthesis model {model!r} answers ({len(content)} characters)")
    return True


def run_smoke(
    *,
    base_url: str,
    base_model: str,
    synthesis_model: str,
    transport: httpx.BaseTransport | None = None,
    timeout_s: float = 120.0,
) -> bool:
    """Exercise the two distinct model paths against one OpenAI-compatible API."""
    if not synthesis_model:
        print("FAIL: no synthesis model is configured", file=sys.stderr)
        return False

    with httpx.Client(
        base_url=f"{base_url.rstrip('/')}/",
        transport=transport,
        timeout=timeout_s,
    ) as client:
        return _react_tool_call_ok(client, base_model) and _munin_answers(client, synthesis_model)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=settings.llm_base_url)
    parser.add_argument("--base-model", default=settings.llm_model)
    parser.add_argument("--synthesis-model", default=settings.synthesis_model)
    args = parser.parse_args(argv)

    try:
        ok = run_smoke(
            base_url=args.base_url,
            base_model=args.base_model,
            synthesis_model=args.synthesis_model,
        )
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        print(f"FAIL: smoke request failed ({type(exc).__name__})", file=sys.stderr)
        return 1

    print("SMOKE PASS" if ok else "SMOKE FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
