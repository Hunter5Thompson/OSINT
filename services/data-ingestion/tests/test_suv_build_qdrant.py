# tests/test_suv_build_qdrant.py
import httpx
import pytest

from suv_structured.build_companies import build_qdrant_points, embed_text
from suv_structured.schemas import Company


def test_qdrant_payload_has_dataset_provenance_no_credibility():
    companies = [Company(name="Hensoldt", suv_url="https://suv.report/hensoldt/",
                         hq_country="Deutschland", products=["TRML-4D"])]
    approved = [{"name": "Hensoldt", "decision": "new", "existing_name": None}]
    points = build_qdrant_points(companies, approved, embed=lambda t: [0.1] * 1024,
                                 now_iso="2026-06-14T00:00:00+00:00")
    p = points[0]
    assert len(p.vector) == 1024
    assert p.payload["source"] == "suv_structured"
    assert p.payload["source_type"] == "dataset"
    assert p.payload["provider"] == "suv.report"
    assert "credibility" not in p.payload                  # read-side only
    assert p.payload["entities"] == [{"name": "Hensoldt"}]
    assert "TRML-4D" in p.payload["content"]


def test_qdrant_point_id_is_deterministic():
    c = [Company(name="X", suv_url="https://suv.report/x/")]
    a = [{"name": "X", "decision": "new", "existing_name": None}]
    id1 = build_qdrant_points(c, a, embed=lambda t: [0.0] * 1024, now_iso="t")[0].id
    id2 = build_qdrant_points(c, a, embed=lambda t: [0.0] * 1024, now_iso="t")[0].id
    assert id1 == id2


def test_only_approved_get_points():
    companies = [Company(name="A", suv_url="ua"), Company(name="B", suv_url="ub")]
    approved = [{"name": "A", "suv_url": "ua", "decision": "new", "existing_name": None}]
    points = build_qdrant_points(companies, approved, embed=lambda t: [0.0] * 1024, now_iso="t")
    assert len(points) == 1


def test_qdrant_point_id_keyed_on_name_not_url():
    """CRITICAL REGRESSION: parse.py gives every company the same directory URL.
    A url-keyed point-id would make all ids identical → 76/77 points overwritten.
    Keying on slug(name) keeps them distinct."""
    url = "https://suv.report/sicherheits-und-verteidigungsindustrie/"
    companies = [Company(name="Rheinmetall AG", suv_url=url),
                 Company(name="Hensoldt", suv_url=url)]
    approved = [
        {"name": "Rheinmetall AG", "suv_url": url, "decision": "new", "existing_name": None},
        {"name": "Hensoldt", "suv_url": url, "decision": "new", "existing_name": None},
    ]
    points = build_qdrant_points(companies, approved, embed=lambda t: [0.0] * 1024, now_iso="t")
    assert len(points) == 2
    assert len({p.id for p in points}) == 2   # distinct ids despite identical suv_url


def test_qdrant_point_id_distinguishes_punctuation_differences():
    # "Rohde & Schwarz" and "Rohde Schwarz" slug-collide under the old lossy slug
    # ("rohde-schwarz"); full-name keying must keep them as distinct point ids.
    companies = [Company(name="Rohde & Schwarz", suv_url="u"),
                 Company(name="Rohde Schwarz", suv_url="u")]
    approved = [{"name": c.name, "suv_url": "u", "decision": "new", "existing_name": None}
                for c in companies]
    points = build_qdrant_points(companies, approved, embed=lambda t: [0.0] * 1024, now_iso="t")
    assert len(points) == 2
    assert len({p.id for p in points}) == 2


@pytest.mark.asyncio
async def test_embed_text_handles_nested_and_flat_tei_shapes():
    nested = httpx.MockTransport(lambda r: httpx.Response(200, json=[[0.5] * 1024]))
    async with httpx.AsyncClient(transport=nested) as client:
        v = await embed_text("x", client=client, tei_embed_url="http://tei")
    assert v == [0.5] * 1024
    flat = httpx.MockTransport(lambda r: httpx.Response(200, json=[0.5] * 1024))
    async with httpx.AsyncClient(transport=flat) as client:
        v2 = await embed_text("x", client=client, tei_embed_url="http://tei")
    assert v2 == [0.5] * 1024
