"""Bounded current research; one instance and one immutable contract per report.

External text is unverified data. Provider responses and exceptions never escape
this boundary: receipts contain fixed codes, not headers, secrets or response bodies.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from functools import partial
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from config import settings
from rag.evidence import EvidenceItem, RetrievalProvenance, SourceRef


class ResearchRun(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of: AwareDatetime
    lookback_hours: int = Field(default=72, ge=1, le=168)
    max_requests: int = Field(default=6, ge=1, le=12)
    max_credits: int = Field(default=6, ge=1, le=12)
    timeout_s: float = Field(default=50, gt=0, le=90)
    # Public web evidence has topic relevance only; never polygon membership.
    scope_key: str = "world"
    spatial_relation: str = "either"


class ResearchAttempt(BaseModel):
    action: Literal["search", "extract", "local_search"]
    status: Literal["succeeded", "empty", "partial", "failed", "blocked"]
    code: str | None = None
    reserved_credits: int = 0
    reported_credits: float | None = None


class ResearchCoverage(BaseModel):
    as_of: datetime
    published_since: datetime
    status: Literal["complete", "partial", "unavailable", "not_requested"] = "complete"
    situation: Literal["evidence_available", "insufficient_evidence", "research_failed"]
    forecast: Literal["not_requested", "not_assessed"] = "not_assessed"
    current_evidence_ids: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    attempts: list[ResearchAttempt] = Field(default_factory=list)
    scope_key: str = "world"
    spatial_basis: Literal["topic_only"] = "topic_only"


class ResearchResult(BaseModel):
    evidence: list[EvidenceItem]
    coverage: ResearchCoverage


def _publication(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            stamp = parsedate_to_datetime(value)
        return stamp.astimezone(UTC) if stamp.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def _public_url(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        if (
            url.scheme != "https"
            or not host
            or url.username
            or url.password
            or url.port not in (None, 443)
            or "." not in host
            or host.endswith((".local", ".internal", ".localhost"))
        ):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return not host.replace(".", "").isdigit()
    except ValueError:
        return False


def _excerpt(text: str, question: str) -> str:
    if len(text) <= 2400:
        return text
    words = set(re.findall(r"\w{3,}", question.lower()))
    paragraphs = list(dict.fromkeys(p.strip() for p in text.split("\n\n") if p.strip()))
    ranked = sorted(
        enumerate(paragraphs), key=lambda pair: -sum(word in pair[1].lower() for word in words)
    )
    selected: list[tuple[int, str]] = []
    remaining = 2390
    for index, paragraph in ranked:
        if remaining <= 50:
            break
        passage = paragraph[: min(remaining, 1000)]
        selected.append((index, passage))
        remaining -= len(passage) + 5
    return "\n[…]\n".join(p for _, p in sorted(selected))[:2400]


class CurrentResearch:
    """search(question) is shared by baseline research and bounded follow-ups."""

    def __init__(
        self,
        run: ResearchRun,
        *,
        client: httpx.AsyncClient,
        api_key: str,
        base_url: str,
        local_reader: Callable[[str, datetime, datetime], Awaitable[list[EvidenceItem]]]
        | None = None,
    ) -> None:
        self._local_reader = local_reader
        self._local_done = False
        self._run = run
        self._client = client
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._deadline = time.monotonic() + run.timeout_s
        self._attempts: list[ResearchAttempt] = []
        self._evidence: dict[str, EvidenceItem] = {}
        self._requests = 0
        self._credits = 0.0
        self._lock = asyncio.Lock()

    async def _request(self, action: Literal["search", "extract"], body: dict) -> dict | None:
        # Reserve before the first await, including failed/unknown paid requests.
        code = None
        if not self._api_key:
            code = "not_configured"
        elif self._requests >= self._run.max_requests or self._credits + 1 > self._run.max_credits:
            code = "budget_exhausted"
        elif time.monotonic() >= self._deadline:
            code = "deadline_exceeded"
        if code:
            self._attempts.append(ResearchAttempt(action=action, status="blocked", code=code))
            return None
        self._requests += 1
        self._credits += 1
        receipt = ResearchAttempt(action=action, status="failed", reserved_credits=1)
        self._attempts.append(receipt)
        try:
            async with asyncio.timeout(min(15, self._deadline - time.monotonic())):
                response = await self._client.post(
                    f"{self._base_url}/{action}",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                    raise ValueError("invalid response")
                usage = data.get("usage", {})
                credits = usage.get("credits") if isinstance(usage, dict) else None
                if isinstance(credits, (int, float)) and 0 <= credits <= 1000:
                    receipt.reported_credits = credits
                    self._credits += max(0, credits - 1)
                receipt.status = "succeeded" if data["results"] else "empty"
                return data
        except httpx.HTTPStatusError as exc:
            receipt.code = {
                401: "authentication_failed",
                403: "access_denied",
                429: "rate_limited",
            }.get(exc.response.status_code, "provider_error")
        except (TimeoutError, httpx.TimeoutException):
            receipt.code = "timeout"
        except httpx.RequestError:
            receipt.code = "transport_error"
        except (ValueError, TypeError):
            receipt.code = "invalid_response"
        return None

    def _result(self) -> ResearchResult:
        since = self._run.as_of - timedelta(hours=self._run.lookback_hours)
        evidence = list(self._evidence.values())
        current = [
            item.evidence_id
            for item in evidence
            if item.evidence_id
            and item.source.published_at is not None
            and since <= item.source.published_at <= self._run.as_of
            and item.retrieval
            and item.retrieval.content_kind in ("fulltext", "fulltext_chunk")
        ]
        errors = any(a.status in ("failed", "blocked", "partial") for a in self._attempts)
        success = any(a.status in ("succeeded", "empty", "partial") for a in self._attempts)
        return ResearchResult(
            evidence=evidence,
            coverage=ResearchCoverage(
                as_of=self._run.as_of,
                published_since=since,
                current_evidence_ids=current,
                situation="evidence_available"
                if current
                else (
                    "insufficient_evidence"
                    if (success and (evidence or not errors))
                    else "research_failed"
                ),
                status=("partial" if success else "unavailable") if errors else "complete",
                gaps=list(dict.fromkeys(a.code for a in self._attempts if a.code)),
                attempts=self._attempts,
                scope_key=self._run.scope_key,
            ).model_copy(deep=True),
        )

    async def _read_local(self, question: str) -> None:
        if self._local_reader is None or self._local_done:
            return
        self._local_done = True
        receipt = ResearchAttempt(action="local_search", status="failed")
        self._attempts.append(receipt)
        if self._requests >= self._run.max_requests or time.monotonic() >= self._deadline:
            receipt.status, receipt.code = "blocked", "budget_exhausted"
            return
        self._requests += 1
        try:
            async with asyncio.timeout(min(10, self._deadline - time.monotonic())):
                items = await self._local_reader(
                    question,
                    self._run.as_of - timedelta(hours=self._run.lookback_hours),
                    self._run.as_of,
                )
            for item in items:
                self._evidence[item.source.url or item.source.source_ref_id] = item
            receipt.status = "succeeded" if items else "empty"
        except Exception:
            receipt.code = "local_corpus_unavailable"

    async def search(self, question: str) -> ResearchResult:
        async with self._lock:
            await self._read_local(question)
            since = self._run.as_of - timedelta(hours=self._run.lookback_hours)
            response = await self._request(
                "search",
                {
                    "query": question[:2000],
                    "topic": "news",
                    "search_depth": "basic",
                    "auto_parameters": False,
                    "include_answer": False,
                    "include_published_date": True,
                    "include_raw_content": False,
                    "include_usage": True,
                    "max_results": 5,
                    "start_date": since.date().isoformat(),
                    "end_date": (self._run.as_of + timedelta(days=1)).date().isoformat(),
                },
            )
            if response is None or not response["results"]:
                return self._result()
            hits = [
                hit
                for hit in response["results"]
                if isinstance(hit, dict)
                and _public_url(hit.get("url"))
                and isinstance(hit.get("title"), str)
                and isinstance(hit.get("content", ""), str)
            ][:5]
            if len(hits) != len(response["results"]):
                self._attempts[-1].status = "partial"
                self._attempts[-1].code = "invalid_results"
            pending = list(
                dict.fromkeys(
                    hit["url"]
                    for hit in hits
                    if hit["url"] not in self._evidence
                    or self._evidence[hit["url"]].retrieval.content_kind != "fulltext"
                )
            )
            if not pending:
                return self._result()
            extracted = await self._request(
                "extract",
                {
                    "urls": pending,
                    "format": "markdown",
                    "extract_depth": "basic",
                    "include_usage": True,
                },
            )
            bodies = {
                row["url"]: row["raw_content"]
                for row in (extracted or {}).get("results", [])
                if isinstance(row, dict)
                and row.get("url") in pending
                and isinstance(row.get("raw_content"), str)
                and row["raw_content"].strip()
            }
            if extracted is not None and any(url not in bodies for url in pending):
                self._attempts[-1].status = "partial"
                self._attempts[-1].code = "original_unavailable"
            for hit in hits:
                url = hit["url"]
                if url not in pending:
                    continue
                text = bodies.get(url, hit.get("content", ""))
                digest = hashlib.sha256(text.encode()).hexdigest()
                identity = hashlib.sha256((url + "\0" + text).encode()).hexdigest()
                published = _publication(hit.get("published_date"))
                attribution = re.search(
                    r"\((Reuters|Associated Press|AP)\)\s*[-–—]", text[:1500], re.I
                )
                lineage = (
                    ("agency:" + ("reuters" if attribution[1].lower() == "reuters" else "ap"))
                    if attribution
                    else url
                )
                self._evidence[url] = EvidenceItem(
                    evidence_id=f"ev-{identity[:24]}",
                    title=hit["title"][:300],
                    excerpt=_excerpt(text, question),
                    relevance_score=0.0,
                    content_hash=digest,
                    source=SourceRef(
                        source_ref_id=identity[:16],
                        source_type="web",
                        provider=urlsplit(url).netloc,
                        url=url,
                        published_at=published,
                    ),
                    retrieval=RetrievalProvenance(
                        retrieved_at=datetime.now(UTC),
                        content_kind="fulltext" if url in bodies else "snippet",
                        content_sha256=digest,
                        original_lineage=lineage,
                        lineage_basis="attribution" if attribution else "url",
                        temporal_basis="provider_publication" if published else "unknown",
                        source_chars=len(text),
                        excerpt_truncated=len(text) > 2400,
                    ),
                )
            return self._result()


@dataclass(frozen=True)
class ResearchContext:
    research: CurrentResearch | None
    public_question: str


@asynccontextmanager
async def open_research(question: str, *, mode: str, scope_key: str, relation: str, scope=None):
    """HTTP ownership belongs to the report lifetime, not individual graph nodes."""
    if mode == "historical":
        yield ResearchContext(None, question)
        return
    from rag.local_current import search_current_corpus
    from rag.public_query import prepare_public_query
    from spatial import RetrievalSpatialRelation

    public_query = await prepare_public_query(question)
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        yield ResearchContext(
            CurrentResearch(
                ResearchRun(
                    as_of=datetime.now(UTC),
                    scope_key=scope_key,
                    spatial_relation=relation,
                    timeout_s=settings.current_research_timeout_s,
                ),
                client=client,
                api_key=settings.tavily_api_key.get_secret_value(),
                base_url=settings.tavily_api_url,
                local_reader=partial(
                    search_current_corpus, scope=scope, relation=RetrievalSpatialRelation(relation)
                ),
            ),
            public_query,
        )
