"""Research behavior at its public interface; only external HTTP is simulated."""

import json
from datetime import UTC, datetime

import httpx

from rag.current import CurrentResearch, ResearchRun

AS_OF = datetime(2026, 11, 6, 14, 35, tzinfo=UTC)
ARTICLE = "https://news.example.org/iran-talks"
BODY = "Iran and regional mediators met on Friday. No agreement was announced."


async def test_current_research_reads_original_article_with_distinct_dates():
    def provider(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/search":
            assert body["include_answer"] is False
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": ARTICLE,
                            "title": "Iran talks continue",
                            "content": "A short teaser",
                            "published_date": "2026-11-06T12:00:00Z",
                            "score": 0.9,
                        }
                    ]
                },
            )
        assert body["urls"] == [ARTICLE]
        return httpx.Response(
            200, json={"results": [{"url": ARTICLE, "raw_content": BODY}], "failed_results": []}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        research = CurrentResearch(
            ResearchRun(as_of=AS_OF),
            client=client,
            api_key="synthetic-key",
            base_url="https://tavily.test",
        )
        result = await research.search("Iran negotiations and possible new attacks")

    assert len(result.evidence) == 1
    item = result.evidence[0]
    assert item.excerpt == BODY
    assert item.source.source_type == "web"
    assert item.source.published_at == datetime(2026, 11, 6, 12, tzinfo=UTC)
    assert item.observed_at is None
    assert item.retrieval.retrieved_at >= AS_OF
    assert item.retrieval.content_kind == "fulltext"
    assert result.coverage.current_evidence_ids == [item.evidence_id]
    assert result.coverage.situation == "evidence_available"
    assert item.verification_status == "unverified"


async def test_extract_partial_success_keeps_failure_visible_and_does_not_claim_original_read():
    def provider(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": ARTICLE,
                            "title": "Iran talks continue",
                            "content": "A short teaser",
                            "published_date": "2026-11-06T12:00:00Z",
                            "score": 0.9,
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [],
                "failed_results": [
                    {"url": ARTICLE, "error": "Blocked by publisher"},
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await CurrentResearch(
            ResearchRun(as_of=AS_OF),
            client=client,
            api_key="fixture",
            base_url="https://tavily.test",
        ).search("Iran negotiations")

    assert result.evidence[0].retrieval.content_kind == "snippet"
    assert result.coverage.status == "partial"
    assert result.coverage.current_evidence_ids == []
    assert result.coverage.situation == "insufficient_evidence"
    assert next(a for a in result.coverage.attempts if a.action == "extract").status == "partial"
    assert (
        next(a for a in result.coverage.attempts if a.action == "extract").code
        == "original_unavailable"
    )


async def test_provider_failure_is_a_redacted_receipt_and_followups_share_budget():
    calls = []

    def provider(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, text="secret-fixture-key", headers={"Retry-After": "120"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        research = CurrentResearch(
            ResearchRun(as_of=AS_OF, max_requests=1),
            client=client,
            api_key="secret-fixture-key",
            base_url="https://tavily.test",
        )
        failed = await research.search("Iran negotiations")
        exhausted = await research.search("Iran followup")
    assert len(calls) == 1
    assert failed.coverage.situation == "research_failed"
    assert failed.coverage.attempts[0].code == "rate_limited"
    assert exhausted.coverage.attempts[-1].code == "budget_exhausted"
    assert exhausted.coverage.as_of == AS_OF
    assert "secret-fixture-key" not in exhausted.model_dump_json()


async def test_unknown_old_future_dates_and_empty_extractions_cannot_pass_current_gate():
    dates = [None, "2026-10-01T12:00:00Z", "2026-11-07T12:00:00Z", "not-a-date"]

    def provider(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": f"{ARTICLE}/{i}",
                            "title": "Iran",
                            "content": "teaser",
                            "published_date": date,
                        }
                        for i, date in enumerate(dates)
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": f"{ARTICLE}/{i}", "raw_content": BODY if i else ""} for i in range(4)
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await CurrentResearch(
            ResearchRun(as_of=AS_OF),
            client=client,
            api_key="fixture",
            base_url="https://tavily.test",
        ).search("Iran")
    assert result.coverage.current_evidence_ids == []
    assert result.coverage.situation == "insufficient_evidence"
    assert result.evidence[0].source.published_at is None
    assert result.evidence[0].retrieval.content_kind == "snippet"
    assert result.evidence[-1].retrieval.temporal_basis == "unknown"


async def test_cancel_propagates_without_retry():
    import asyncio

    import pytest

    calls = []

    async def provider(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise asyncio.CancelledError()

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        research = CurrentResearch(
            ResearchRun(as_of=AS_OF),
            client=client,
            api_key="fixture",
            base_url="https://tavily.test",
        )
        with pytest.raises(asyncio.CancelledError):
            await research.search("Iran")
    assert len(calls) == 1


async def test_empty_search_and_missing_key_never_extract():
    calls = []

    def provider(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await CurrentResearch(
            ResearchRun(as_of=AS_OF),
            client=client,
            api_key="fixture",
            base_url="https://tavily.test",
        ).search("Iran")
        disabled = await CurrentResearch(
            ResearchRun(as_of=AS_OF), client=client, api_key="", base_url="https://tavily.test"
        ).search("Iran")
    assert len(calls) == 3
    assert result.coverage.situation == "insufficient_evidence"
    assert disabled.coverage.situation == "research_failed"
    assert disabled.coverage.attempts[0].code == "not_configured"


async def test_untrusted_rows_are_filtered_and_followups_do_not_reread_cached_originals():
    calls = []

    def provider(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        None,
                        {"url": "http://127.0.0.1/admin"},
                        {"url": "https://user:password@example.org/"},
                        {
                            "url": ARTICLE,
                            "title": "Iran",
                            "content": "teaser",
                            "published_date": "2026-11-06T12:00:00Z",
                        },
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": ARTICLE, "raw_content": BODY},
                    {"url": "https://unexpected.example.org", "raw_content": "not requested"},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        research = CurrentResearch(
            ResearchRun(as_of=AS_OF),
            client=client,
            api_key="fixture",
            base_url="https://tavily.test",
        )
        await research.search("Iran")
        result = await research.search("Iran followup")
    extracts = [r for r in calls if r.url.path == "/extract"]
    assert len(extracts) == 1
    assert json.loads(extracts[0].content)["urls"] == [ARTICLE]
    assert len(result.evidence) == 1
    assert result.evidence[0].retrieval.content_kind == "fulltext"
    assert result.coverage.status == "partial"
    assert "invalid_results" in result.coverage.gaps


async def test_real_provider_rfc_publication_date_and_large_original_are_preserved():
    article = "Navigation menu\n\n" * 400 + BODY + "\n\n" + "Footer navigation\n" * 400

    def provider(request):
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": ARTICLE,
                            "title": "Iran talks",
                            "content": "teaser",
                            "published_date": "Fri, 06 Nov 2026 12:00:00 GMT",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"results": [{"url": ARTICLE, "raw_content": article}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as c:
        result = await CurrentResearch(
            ResearchRun(as_of=AS_OF), client=c, api_key="fixture", base_url="https://tavily.test"
        ).search("Iran")
    assert result.coverage.current_evidence_ids
    assert BODY in result.evidence[0].excerpt
    assert len(result.evidence[0].excerpt) <= 2400
    assert result.evidence[0].retrieval.excerpt_truncated is True


async def test_syndicated_copies_keep_one_explicit_origin():
    urls = [ARTICLE, "https://another.example.org/copy"]

    def provider(request):
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": url,
                            "title": "Iran talks",
                            "content": "teaser",
                            "published_date": "2026-11-06T12:00:00Z",
                        }
                        for url in urls
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": urls[0], "raw_content": "LONDON (Reuters) - " + BODY},
                    {"url": urls[1], "raw_content": "LONDON (Reuters) - " + BODY + " Read more."},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as c:
        result = await CurrentResearch(
            ResearchRun(as_of=AS_OF), client=c, api_key="fixture", base_url="https://tavily.test"
        ).search("Iran")
    assert {e.retrieval.original_lineage for e in result.evidence} == {"agency:reuters"}
    assert all(e.retrieval.lineage_basis == "attribution" for e in result.evidence)


async def test_owned_corpus_remains_available_when_external_search_is_not_configured():
    from rag.evidence import EvidenceItem, RetrievalProvenance, SourceRef

    async def local(question, since, as_of):
        assert since == AS_OF.replace(day=3)
        assert as_of == AS_OF
        return [
            EvidenceItem(
                evidence_id="ev-local",
                title="Iran",
                excerpt=BODY,
                relevance_score=1,
                source=SourceRef(
                    source_ref_id="local", source_type="rss", provider="bbc", published_at=AS_OF
                ),
                retrieval=RetrievalProvenance(
                    retrieved_at=AS_OF,
                    content_kind="fulltext_chunk",
                    content_sha256="a" * 64,
                    original_lineage=ARTICLE,
                ),
            )
        ]

    async with httpx.AsyncClient() as c:
        result = await CurrentResearch(
            ResearchRun(as_of=AS_OF),
            client=c,
            api_key="",
            base_url="https://tavily.test",
            local_reader=local,
        ).search("Iran")
    assert result.coverage.current_evidence_ids == ["ev-local"]
    assert result.coverage.status == "partial"
    assert result.coverage.attempts[0].action == "local_search"
    assert result.coverage.attempts[-1].code == "not_configured"


async def test_topic_only_web_evidence_cannot_authorize_scoped_occurrence():
    def provider(request):
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": ARTICLE,
                            "title": "London",
                            "content": BODY,
                            "published_date": "2026-11-06T12:00:00Z",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"results": [{"url": ARTICLE, "raw_content": BODY}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as c:
        result = await CurrentResearch(
            ResearchRun(as_of=AS_OF, scope_key="country:IRN", spatial_relation="occurrence"),
            client=c,
            api_key="fixture",
            base_url="https://tavily.test",
        ).search("Iran events")
    assert result.coverage.situation == "insufficient_evidence"
    assert "spatial_occurrence_unproven" in result.coverage.gaps


async def test_baseline_always_searches_for_counterevidence_and_records_the_trigger():
    queries = []

    def provider(request):
        if request.url.path == "/search":
            queries.append(json.loads(request.content)["query"])
        return httpx.Response(200, json={"results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as c:
        result = await CurrentResearch(
            ResearchRun(as_of=AS_OF), client=c, api_key="fixture", base_url="https://tavily.test"
        ).search("Iran military strikes")
    assert len(queries) >= 2
    assert "contrary evidence" in queries[1]
    assert result.coverage.attempts[0].trigger == "baseline"
    assert result.coverage.attempts[1].trigger == "counterevidence"
    assert result.coverage.attempts[1].query == queries[1]


async def test_thin_results_expand_only_within_the_pinned_window():
    windows = []

    def provider(request):
        if request.url.path == "/search":
            body = json.loads(request.content)
            windows.append(body["start_date"])
            return httpx.Response(200, json={"results": []})
        raise AssertionError("No extraction without results")

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as c:
        research = CurrentResearch(
            ResearchRun(as_of=AS_OF, lookback_hours=24, expanded_lookback_hours=168),
            client=c,
            api_key="fixture",
            base_url="https://tavily.test",
        )
        result = await research.search("Iran")
        later = await research.search("Iran official statements")
    assert windows == ["2026-11-05", "2026-11-05", "2026-10-30", "2026-10-30"]
    assert result.coverage.as_of == later.coverage.as_of == AS_OF
    assert "window_expanded" in later.coverage.gaps
    assert result.coverage.published_since == AS_OF.replace(month=10, day=30)


async def test_original_publication_conflict_excludes_a_freshly_indexed_old_article():
    def provider(request):
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": ARTICLE,
                            "title": "Iran",
                            "content": BODY,
                            "published_date": "2026-11-06T12:00:00Z",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": ARTICLE,
                        "raw_content": "Published: May 2, 2026\n\n" + BODY,
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await CurrentResearch(
            ResearchRun(as_of=AS_OF),
            client=client,
            api_key="fixture",
            base_url="https://tavily.test",
        ).search("Iran")
    assert result.coverage.current_evidence_ids == []
    assert "publication_conflict" in result.coverage.gaps
    assert result.evidence[0].retrieval.publication_check == "conflict"


async def test_oversized_provider_response_is_bounded_and_has_a_redacted_receipt():
    def provider(request):
        return httpx.Response(200, json={"results": [], "padding": "x" * 2_100_000})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await CurrentResearch(
            ResearchRun(as_of=AS_OF),
            client=client,
            api_key="fixture",
            base_url="https://tavily.test",
        ).search("Iran")
    assert result.coverage.situation == "research_failed"
    assert result.coverage.attempts[0].code == "response_too_large"


async def test_a_long_single_paragraph_is_never_cut_before_a_late_negation():
    text = "Iran officials discussed " + "the disputed report " * 200 + "but denied it entirely."

    def provider(request):
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": ARTICLE,
                            "title": "Iran",
                            "content": "teaser",
                            "published_date": "2026-11-06T12:00:00Z",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"results": [{"url": ARTICLE, "raw_content": text}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await CurrentResearch(
            ResearchRun(as_of=AS_OF),
            client=client,
            api_key="fixture",
            base_url="https://tavily.test",
        ).search("Iran")
    assert all(
        not item.excerpt or "but denied it entirely." in item.excerpt for item in result.evidence
    )
    assert result.coverage.current_evidence_ids == []
    assert "excerpt_unavailable" in result.coverage.gaps


async def test_operator_source_selection_is_enforced_and_disclosed():
    def provider(request):
        if request.url.path == "/search":
            assert json.loads(request.content)["include_domains"] == ["news.example.org"]
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": "https://redirect.example.com/wrapper",
                            "title": "Iran",
                            "content": BODY,
                            "published_date": "2026-11-06T12:00:00Z",
                        }
                    ]
                },
            )
        raise AssertionError("An out-of-policy publisher must not be extracted")

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await CurrentResearch(
            ResearchRun(as_of=AS_OF, search_domains=("news.example.org",)),
            client=client,
            api_key="fixture",
            base_url="https://tavily.test",
        ).search("Iran")
    assert result.coverage.search_domains == ["news.example.org"]
    assert result.coverage.current_evidence_ids == []
