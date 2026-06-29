#!/usr/bin/env python3
"""Gating check: does the Spark vLLM satisfy ODIN's data-ingestion contract?

Mirrors services/data-ingestion/pipeline.py:_call_vllm + scheduler.check_ingestion_llm EXACTLY:
  - model name must appear in /v1/models data[].id  (scheduler: ingestion_llm_model_mismatch)
  - response_format json_schema strict with the REAL _RESPONSE_SCHEMA
  - chat_template_kwargs enable_thinking False, temperature 0.1, max_tokens 2000
PASS requires HTTP 200 (a 4xx/422 = ODIN ExtractionConfigError = hard ingestion failure)
AND schema-shaped, parseable JSON. Run AFTER the NVFP4 cutover; on FAIL -> rollback.
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://192.168.178.39:8000"
MODEL = "Qwen/Qwen3.6-35B-A3B"

# Verbatim copy of services/data-ingestion/pipeline.py:_RESPONSE_SCHEMA (lines 236-286)
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "codebook_type": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "confidence": {"type": "number"},
                    "timestamp": {"type": "string"},
                },
                "required": ["title", "summary", "codebook_type", "severity", "confidence"],
            },
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": [
                        "person", "organization", "location", "weapon_system",
                        "satellite", "vessel", "aircraft", "military_unit",
                    ]},
                    "confidence": {"type": "number"},
                },
                "required": ["name", "type"],
            },
        },
        "locations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "country": {"type": "string"},
                },
                "required": ["name", "country"],
            },
        },
    },
    "required": ["events", "entities", "locations"],
}

SYSTEM = ("You are an OSINT intelligence extraction engine. Extract events, entities and "
          "locations from the provided text and return ONLY strict JSON per the schema.")
USER = ("Source: https://example.org/news\n\nText: Russian forces launched a Shahed drone "
        "attack on Kharkiv overnight; Ukrainian air defense intercepted 12 drones. NATO "
        "Secretary General condemned the strike and the Bundeswehr announced a Patriot "
        "battery deployment to the eastern flank.")


def _get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post(url, payload, timeout=120):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode())


def main() -> None:
    ok = True

    # [1] scheduler.check_ingestion_llm: model id present in /v1/models
    try:
        ids = [m["id"] for m in _get(f"{BASE}/v1/models")["data"]]
        c1 = MODEL in ids
        print(f"[1] /v1/models lists '{MODEL}': {'PASS' if c1 else 'FAIL'}  (got {ids})")
        ok &= c1
    except Exception as e:  # noqa: BLE001
        print(f"[1] /v1/models FAIL — {e!r}")
        sys.exit(1)

    # [2] exact _call_vllm guided-JSON request
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}],
        "temperature": 0.1,
        "max_tokens": 2000,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "intelligence_extraction", "schema": SCHEMA, "strict": True},
        },
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        status, resp = _post(f"{BASE}/v1/chat/completions", payload)
    except urllib.error.HTTPError as e:
        body = e.read()[:400].decode(errors="replace")
        print(f"[2] guided-JSON request: FAIL — HTTP {e.code} "
              f"(= ODIN ExtractionConfigError, hard fail)\n    body: {body}")
        print("\nRESULT: ❌ CONTRACT BROKEN — roll back to BF16")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"[2] guided-JSON request: FAIL — {e!r}")
        sys.exit(1)

    content = resp["choices"][0]["message"]["content"] or ""
    try:
        parsed = json.loads(content)
        shaped = (all(k in parsed for k in ("events", "entities", "locations"))
                  and all(isinstance(parsed[k], list) for k in ("events", "entities", "locations")))
        # spot-check enum adherence (strict guided decoding must honor it)
        sev_ok = all(ev.get("severity") in ("low", "medium", "high", "critical")
                     for ev in parsed.get("events", []))
        c2 = shaped and sev_ok
        print(f"[2] json_schema strict -> HTTP {status}, parseable, schema-shaped, enums valid: "
              f"{'PASS' if c2 else 'FAIL'}")
        print(f"    sample: {json.dumps(parsed, ensure_ascii=False)[:280]}")
    except Exception as e:  # noqa: BLE001
        c2 = False
        print(f"[2] json_schema strict -> 200 but JSON parse FAIL: {e}\n    raw: {content[:200]}")
    ok &= c2

    print("\nRESULT:", "✅ CONTRACT OK — NVFP4 satisfies the ODIN ingestion contract"
          if ok else "❌ CONTRACT BROKEN — roll back to BF16")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
