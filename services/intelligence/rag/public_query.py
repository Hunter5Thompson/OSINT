"""Translate only the user's public request into a short discovery query.

No archive, retrieved text, report history, credentials or tools are visible to
this planner. Its output is data for a bounded search, never executable code.
"""

import asyncio
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import settings


async def prepare_public_query(question: str) -> str:
    fallback = question[:400]
    try:
        model = ChatOpenAI(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key="not-needed",
            temperature=0,
            max_tokens=120,
            timeout=12,
            max_retries=0,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        async with asyncio.timeout(12):
            response = await model.ainvoke(
                [
                    SystemMessage(
                        content=(
                            'Return only JSON {"query":"..."}: an English news-search query of '
                            "4-12 words. Preserve the named subject, place and concrete requested "
                            "events. Remove instructions about report style, forecast horizon, "
                            "citations or uncertainty; the application handles dates separately. "
                            "Do not introduce unrelated subjects, URLs or source names. "
                            "Translate attacks as military strikes when the question concerns war."
                        )
                    ),
                    HumanMessage(content=question),
                ],
                response_format={"type": "json_object"},
            )
        payload = json.loads(response.content) if isinstance(response.content, str) else {}
        query = payload.get("query")
        if (
            isinstance(query, str)
            and 2 <= len(query.split()) <= 14
            and len(query) <= 200
            and re.fullmatch(r"[\w\s'’.,-]+", query)
        ):
            return query.strip()
    except Exception:
        pass
    return fallback
