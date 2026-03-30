"""classify_event tool — on-demand event classification via IntelligenceExtractor."""

from __future__ import annotations

import structlog
from langchain_core.tools import tool

from codebook.extractor import IntelligenceExtractor, IntelligenceExtractionResult
from config import settings

log = structlog.get_logger(__name__)

_extractor: IntelligenceExtractor | None = None


def _get_extractor() -> IntelligenceExtractor:
    """Lazy-init the IntelligenceExtractor singleton."""
    global _extractor
    if _extractor is None:
        _extractor = IntelligenceExtractor(
            vllm_url=settings.vllm_url,
            vllm_model=settings.vllm_model,
        )
    return _extractor


def _format_extraction_result(result: IntelligenceExtractionResult) -> str:
    """Format extraction result as readable text for the agent."""
    if not result.events and not result.entities:
        return "No events or entities detected in the provided text."

    lines = []
    if result.events:
        lines.append("[Classified Events]")
        for ev in result.events:
            lines.append(
                f"  - {ev.title} | type: {ev.codebook_type} | "
                f"severity: {ev.severity} | confidence: {ev.confidence:.1f}"
            )
            if ev.summary:
                lines.append(f"    {ev.summary}")

    if result.entities:
        lines.append("[Extracted Entities]")
        for ent in result.entities:
            lines.append(f"  - {ent.name} ({ent.type}, confidence: {ent.confidence:.1f})")

    if result.locations:
        lines.append("[Locations]")
        for loc in result.locations:
            lines.append(f"  - {loc.name}, {loc.country}")

    return "\n".join(lines)


@tool
async def classify_event(text: str, context: str = "") -> str:
    """Classify a piece of text using the intelligence event codebook.
    Returns event type, severity, confidence, and extracted entities.

    Args:
        text: The text to classify (headline, paragraph, or article).
        context: Optional context about the source or region.
    """
    if not text or not text.strip():
        return "Please provide text to classify."

    try:
        extractor = _get_extractor()
        result = await extractor.extract(text=text, source_url=context)
        return _format_extraction_result(result)
    except Exception as e:
        log.warning("classify_event_failed", error=str(e))
        return f"Classification failed: {e}"
