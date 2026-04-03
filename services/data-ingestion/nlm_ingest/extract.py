from __future__ import annotations

import json
from pathlib import Path

import httpx
import structlog

from nlm_ingest.schemas import (
    Claim,
    Entity,
    Extraction,
    Relation,
    Transcript,
)

log = structlog.get_logger()

CLAUDE_BUDGET_PER_RUN = 50_000
PROMPT_DIR = Path(__file__).parent / "prompts"


def load_prompt(version: str) -> str:
    path = PROMPT_DIR / f"extraction_{version}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text()


def extract_context(full_text: str, target: str, radius: int = 500) -> str:
    idx = full_text.find(target)
    if idx == -1:
        return full_text[: radius * 2]
    start = max(0, idx - radius)
    end = min(len(full_text), idx + len(target) + radius)
    return full_text[start:end]


async def extract_with_qwen(
    transcript: Transcript,
    metadata: dict,
    client: httpx.AsyncClient,
    vllm_url: str,
    vllm_model: str,
    prompt_version: str = "v1",
) -> Extraction:
    prompt_template = load_prompt(prompt_version)
    # Use explicit replacement instead of str.format() — the prompt contains
    # JSON example blocks with bare braces that would cause KeyError.
    prompt = (
        prompt_template
        .replace("{source_name}", metadata.get("source_name", "unknown"))
        .replace("{title}", metadata.get("title", "untitled"))
        .replace("{transcript_text}", transcript.full_text[:16_000])
    )

    payload = {
        "model": vllm_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 4000,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    response = await client.post(
        f"{vllm_url}/chat/completions",
        json=payload,
        timeout=120.0,
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"]
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    data = json.loads(content)

    return Extraction(
        notebook_id=transcript.notebook_id,
        entities=[Entity(**e) for e in data.get("entities", [])],
        relations=[Relation(**r) for r in data.get("relations", [])],
        claims=[Claim(**c) for c in data.get("claims", [])],
        extraction_model=vllm_model,
        prompt_version=prompt_version,
    )


async def review_with_claude(
    extraction: Extraction,
    transcript: Transcript,
    claude_client,
    claude_model: str,
) -> Extraction:
    low_conf_claims = [c for c in extraction.claims if c.confidence < 0.7]
    if not low_conf_claims:
        log.info("claude_review_skip", reason="no low-confidence claims")
        return extraction

    token_budget = CLAUDE_BUDGET_PER_RUN
    reviewed_count = 0

    for claim in low_conf_claims:
        context_window = extract_context(
            transcript.full_text, claim.statement[:80], radius=500
        )
        # Estimate input tokens (context // 4) plus the 200-token response budget.
        estimated_tokens = len(context_window) // 4 + 200
        if token_budget < estimated_tokens:
            log.info("claude_budget_exhausted", reviewed=reviewed_count)
            break
        token_budget -= estimated_tokens

        try:
            message = await claude_client.messages.create(
                model=claude_model,
                max_tokens=200,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Verify this claim extracted from a think-tank podcast transcript.\n\n"
                            f"Claim: \"{claim.statement}\"\n"
                            f"Type: {claim.type} | Polarity: {claim.polarity}\n\n"
                            f"Transcript context:\n{context_window}\n\n"
                            f'Return JSON: {{"verdict": "confirmed|rejected|modified",'
                            f' "confidence": 0.0-1.0}}'
                        ),
                    }
                ],
            )
            result = json.loads(message.content[0].text)
            if result.get("verdict") == "rejected":
                claim.confidence = 0.0
            else:
                claim.confidence = result.get("confidence", claim.confidence)
            reviewed_count += 1
        except Exception:
            log.warning("claude_review_failed", claim=claim.statement[:50])
            continue

    log.info("claude_review_done", reviewed=reviewed_count, budget_remaining=token_budget)
    return extraction
