"""Synthesis Agent — produces final intelligence reports."""

from langchain_core.messages import SystemMessage
from langchain_ollama import ChatOllama

from config import settings

SYSTEM_PROMPT = """You are an intelligence report synthesizer.
Your role is to combine OSINT findings and analytical assessments into
a coherent, actionable intelligence report.
Structure your report with:
1. Executive Summary (2-3 sentences)
2. Key Findings (bullet points)
3. Threat Assessment (CRITICAL/HIGH/ELEVATED/MODERATE with justification)
4. Confidence Level (0.0-1.0 based on source quality and corroboration)
5. Recommended Actions (if applicable)
Be precise and avoid speculation beyond what the evidence supports."""


def create_synthesis_llm() -> ChatOllama:
    """Create LLM instance for the Synthesis agent."""
    return ChatOllama(
        base_url=settings.ollama_url,
        model=settings.ollama_model,
        temperature=0.1,
    )


def get_system_message() -> SystemMessage:
    return SystemMessage(content=SYSTEM_PROMPT)
