"""OSINT Agent — gathers open-source intelligence data."""

import structlog
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI

from config import settings

logger = structlog.get_logger()

SYSTEM_PROMPT = """You are an OSINT (Open Source Intelligence) analyst.
Your role is to gather and organize relevant information from available sources.
Focus on factual, verifiable information from credible sources.
Structure your findings clearly with source attribution.
Be concise but thorough."""


def create_osint_llm() -> ChatOpenAI:
    """Create LLM instance for the OSINT agent."""
    return ChatOpenAI(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=0.3,
        api_key="not-needed",
    )


def get_system_message() -> SystemMessage:
    return SystemMessage(content=SYSTEM_PROMPT)
