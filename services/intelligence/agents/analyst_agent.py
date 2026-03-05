"""Analyst Agent — analyzes OSINT data and produces threat assessments."""

from langchain_core.messages import SystemMessage
from langchain_ollama import ChatOllama

from config import settings

SYSTEM_PROMPT = """You are a senior intelligence analyst.
Your role is to analyze OSINT findings and produce threat assessments.
Rate threats as: CRITICAL, HIGH, ELEVATED, or MODERATE.
Identify patterns, correlations, and potential escalation risks.
Be objective and evidence-based in your analysis.
Always cite the sources that support your assessment."""


def create_analyst_llm() -> ChatOllama:
    """Create LLM instance for the Analyst agent."""
    return ChatOllama(
        base_url=settings.ollama_url,
        model=settings.ollama_model,
        temperature=0.2,
    )


def get_system_message() -> SystemMessage:
    return SystemMessage(content=SYSTEM_PROMPT)
