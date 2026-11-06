"""Bounded current research; one instance and one immutable contract per report.

External text is unverified data. Provider responses and exceptions never escape
this boundary: receipts contain fixed codes, not headers, secrets or response bodies.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
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
from uuid import uuid4

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from config import settings
from rag.evidence import EvidenceItem, RetrievalProvenance, SourceRef, eligible_current_evidence
from rag.excerpts import select_excerpt
from rag.publication import check_publication


class ResearchRun(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of: AwareDatetime
    lookback_hours: int = Field(default=72, ge=1, le=168)
    expanded_lookback_hours: int = Field(default=168, ge=1, le=168)
    max_requests: int = Field(default=6, ge=1, le=12)
    max_credits: int = Field(default=6, ge=1, le=12)
    timeout_s: float = Field(default=50, gt=0, le=90)
    # Public web evidence has topic relevance only; never polygon membership.
    scope_key: str = "world"
    spatial_relation: Literal["about", "occurrence", "either"] = "either"
    search_domains: tuple[str, ...] = Field(default=(), max_length=40)

    @model_validator(mode="after")
    def bounded_window(self):
        if self.expanded_lookback_hours < self.lookback_hours:
            raise ValueError("Expanded window cannot be shorter than the primary window")
        return self


class SourceRead(BaseModel):
    url: str
    status: Literal["succeeded", "failed"]
    code: str | None = None


class ResearchAttempt(BaseModel):
    action: Literal["search", "extract", "local_search"]
    status: Literal["succeeded", "empty", "partial", "failed", "blocked"]
    code: str | None = None
    trigger: Literal["baseline", "counterevidence", "followup", "expanded_window"] = "baseline"
    query: str | None = None
    started_at: datetime | None = None
    source_reads: list[SourceRead] = Field(default_factory=list)
    reserved_credits: int = 0
    reported_credits: float | None = None


class ResearchCoverage(BaseModel):
    run_id: str | None = None
    search_domains: list[str] = Field(default_factory=list)
    as_of: datetime
    published_since: datetime
    status: Literal["complete", "partial", "unavailable", "not_requested"] = "complete"
    situation: Literal["evidence_available", "insufficient_evidence", "research_failed"]
    forecast: Literal["not_requested", "not_assessed"] = "not_assessed"
    current_evidence_ids: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    attempts: list[ResearchAttempt] = Field(default_factory=list)
    scope_key: str = "world"
    spatial_basis: Literal["topic_only", "scoped"] = "topic_only"


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
        self._lookback_hours = run.lookback_hours
        self._window_expanded = False
        self._provider_blocked: str | None = None
        self._run_id = uuid4().hex
        self._first_search = True
        self._trigger = "baseline"
        self._extracted_urls: set[str] = set()
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
        if self._requests >= self._run.max_requests or self._credits + 1 > self._run.max_credits:
            code = "budget_exhausted"
        elif self._provider_blocked:
            code = self._provider_blocked
        elif not self._api_key:
            code = "not_configured"
        elif time.monotonic() >= self._deadline:
            code = "deadline_exceeded"
        if code:
            self._attempts.append(
                ResearchAttempt(
                    action=action,
                    status="blocked",
                    code=code,
                    trigger=self._trigger,
                    query=body.get("query"),
                )
            )
            return None
        self._requests += 1
        self._credits += 1
        receipt = ResearchAttempt(
            action=action,
            status="failed",
            reserved_credits=1,
            trigger=self._trigger,
            query=body.get("query"),
            started_at=datetime.now(UTC),
        )
        self._attempts.append(receipt)
        try:
            async with asyncio.timeout(min(15, self._deadline - time.monotonic())):
                async with self._client.stream(
                    "POST",
                    f"{self._base_url}/{action}",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=body,
                ) as response:
                    response.raise_for_status()
                    payload = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        if len(payload) + len(chunk) > 2 * 1024 * 1024:
                            receipt.code = "response_too_large"
                            return None
                        payload.extend(chunk)
                    data = json.loads(payload)
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
            if exc.response.status_code in (401, 403, 429):
                self._provider_blocked = receipt.code
        except (TimeoutError, httpx.TimeoutException):
            receipt.code = "timeout"
        except httpx.RequestError:
            receipt.code = "transport_error"
        except (ValueError, TypeError):
            receipt.code = "invalid_response"
        return None

    def _result(self) -> ResearchResult:
        since = self._run.as_of - timedelta(hours=self._lookback_hours)
        evidence = list(self._evidence.values())
        require_occurrence = (
            self._run.scope_key != "world" and self._run.spatial_relation == "occurrence"
        )
        current = [
            item.evidence_id
            for item in evidence
            if item.evidence_id
            and eligible_current_evidence(item, since, self._run.as_of)
            and (
                not require_occurrence
                or (item.retrieval is not None and item.retrieval.spatial_basis == "scoped")
            )
        ]
        date_conflict = any(
            item.retrieval and item.retrieval.publication_check == "conflict" for item in evidence
        )
        occurrence_unproven = require_occurrence and not current
        errors = any(a.status in ("failed", "blocked", "partial") for a in self._attempts)
        success = any(a.status in ("succeeded", "empty", "partial") for a in self._attempts)
        return ResearchResult(
            evidence=evidence,
            coverage=ResearchCoverage(
                run_id=self._run_id,
                search_domains=list(self._run.search_domains),
                as_of=self._run.as_of,
                published_since=since,
                current_evidence_ids=current,
                situation="insufficient_evidence"
                if occurrence_unproven
                else "evidence_available"
                if current
                else (
                    "insufficient_evidence"
                    if (success and (evidence or not errors))
                    else "research_failed"
                ),
                status=("partial" if success else "unavailable")
                if errors or occurrence_unproven or self._window_expanded or date_conflict
                else "complete",
                gaps=list(dict.fromkeys(a.code for a in self._attempts if a.code))
                + (["spatial_occurrence_unproven"] if occurrence_unproven else [])
                + (["window_expanded"] if self._window_expanded else [])
                + (["publication_conflict"] if date_conflict else [])
                + (["excerpt_unavailable"] if any(not e.excerpt.strip() for e in evidence) else []),
                attempts=self._attempts,
                scope_key=self._run.scope_key,
                spatial_basis="scoped" if require_occurrence and current else "topic_only",
            ).model_copy(deep=True),
        )

    async def _read_local(self, question: str) -> None:
        if self._local_reader is None or self._local_done:
            return
        self._local_done = True
        receipt = ResearchAttempt(
            action="local_search",
            status="failed",
            query=question,
            started_at=datetime.now(UTC),
            trigger=self._trigger,
        )
        self._attempts.append(receipt)
        if self._requests >= self._run.max_requests or time.monotonic() >= self._deadline:
            receipt.status, receipt.code = "blocked", "budget_exhausted"
            return
        self._requests += 1
        try:
            async with asyncio.timeout(min(10, self._deadline - time.monotonic())):
                items = await self._local_reader(
                    question,
                    self._run.as_of - timedelta(hours=self._lookback_hours),
                    self._run.as_of,
                )
            for item in items:
                self._evidence[item.source.url or item.source.source_ref_id] = item
            receipt.status = "succeeded" if items else "empty"
        except Exception:
            receipt.code = "local_corpus_unavailable"

    async def _search_web(self, question: str) -> None:
        since = self._run.as_of - timedelta(hours=self._lookback_hours)
        response = await self._request(
            "search",
            {
                "query": question[:2000],
                "topic": "news",
                "search_depth": "basic",
                "auto_parameters": False,
                "include_answer": False,
                "include_published_date": True,
                "filter_by_published_date": True,
                "include_domains": list(self._run.search_domains),
                "include_raw_content": False,
                "include_usage": True,
                "max_results": 5,
                "start_date": since.date().isoformat(),
                "end_date": (self._run.as_of + timedelta(days=1)).date().isoformat(),
            },
        )
        if response is None or not response["results"]:
            return
        hits = [
            hit
            for hit in response["results"]
            if isinstance(hit, dict)
            and _public_url(hit.get("url"))
            and (
                not self._run.search_domains
                or any(
                    (urlsplit(hit["url"]).hostname or "").lower() == domain
                    or (urlsplit(hit["url"]).hostname or "").lower().endswith("." + domain)
                    for domain in self._run.search_domains
                )
            )
            and isinstance(hit.get("title"), str)
            and isinstance(hit.get("content", ""), str)
        ][:5]
        if len(hits) != len(response["results"]):
            self._attempts[-1].status = "partial"
            self._attempts[-1].code = "invalid_results"
        pending = list(
            dict.fromkeys(hit["url"] for hit in hits if hit["url"] not in self._extracted_urls)
        )
        if not pending:
            return
        self._extracted_urls.update(pending)
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
        if self._attempts[-1].action == "extract":
            failures = {
                row.get("url"): str(row.get("error", "")).lower()
                for row in (extracted or {}).get("failed_results", [])
                if isinstance(row, dict) and isinstance(row.get("url"), str)
            }
            for url in pending:
                error = failures.get(url, "")
                code = next(
                    (
                        label
                        for word, label in [
                            ("paywall", "paywall"),
                            ("403", "access_denied"),
                            ("blocked", "access_denied"),
                            ("timeout", "timeout"),
                            ("robots", "robots_denied"),
                        ]
                        if word in error
                    ),
                    self._attempts[-1].code or "original_unavailable",
                )
                self._attempts[-1].source_reads.append(
                    SourceRead(
                        url=url,
                        status="succeeded" if url in bodies else "failed",
                        code=None if url in bodies else code,
                    )
                )
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
            publication = check_publication(text, published)
            attribution = re.search(r"\((Reuters|Associated Press|AP)\)\s*[-–—]", text[:1500], re.I)
            lineage = (
                ("agency:" + ("reuters" if attribution[1].lower() == "reuters" else "ap"))
                if attribution
                else url
            )
            self._evidence[url] = EvidenceItem(
                evidence_id=f"ev-{identity[:24]}",
                title=hit["title"][:300],
                excerpt=select_excerpt(text, question),
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
                    publication_check=publication.status,
                    original_publication_date=publication.original_date,
                    original_lineage=lineage,
                    lineage_basis="attribution" if attribution else "url",
                    temporal_basis="provider_publication" if published else "unknown",
                    source_chars=len(text),
                    excerpt_truncated=len(text) > 2400,
                ),
            )
        return

    async def search(self, question: str) -> ResearchResult:
        async with self._lock:
            first = self._first_search
            self._first_search = False
            self._trigger = "baseline" if first else "followup"
            await self._read_local(question)
            await self._search_web(question)
            if first:
                self._trigger = "counterevidence"
                await self._search_web(question + " denials contrary evidence official statements")
                if (
                    not self._result().coverage.current_evidence_ids
                    and self._run.expanded_lookback_hours > self._lookback_hours
                    and any(
                        a.action == "search" and a.status in ("succeeded", "empty")
                        for a in self._attempts
                    )
                ):
                    self._lookback_hours = self._run.expanded_lookback_hours
                    self._window_expanded = True
                    self._trigger = "expanded_window"
                    self._local_done = False
                    await self._read_local(question)
                    await self._search_web(question)
            return self._result()


@dataclass(frozen=True)
class ResearchContext:
    research: CurrentResearch | None
    public_question: str


@asynccontextmanager
async def open_research(
    question: str,
    *,
    mode: str,
    scope_key: str,
    relation: str,
    scope=None,
    as_of: datetime | None = None,
):
    """HTTP ownership belongs to the report lifetime, not individual graph nodes."""
    if mode == "historical":
        yield ResearchContext(None, question)
        return
    from rag.local_current import search_current_corpus
    from rag.public_query import prepare_public_query
    from spatial import RetrievalSpatialRelation

    pinned_time = as_of or datetime.now(UTC)
    public_query = await prepare_public_query(question)
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        yield ResearchContext(
            CurrentResearch(
                ResearchRun(
                    as_of=pinned_time,
                    scope_key=scope_key,
                    spatial_relation=relation,
                    search_domains=settings.current_research_domains,
                    timeout_s=settings.current_research_timeout_s,
                    lookback_hours=settings.current_research_lookback_hours,
                    expanded_lookback_hours=settings.current_research_expanded_lookback_hours,
                    max_requests=settings.current_research_max_requests,
                    max_credits=settings.current_research_max_credits,
                ),
                client=client,
                api_key=settings.current_search_key.get_secret_value(),
                base_url=settings.tavily_api_url,
                local_reader=partial(
                    search_current_corpus, scope=scope, relation=RetrievalSpatialRelation(relation)
                ),
            ),
            public_query,
        )
