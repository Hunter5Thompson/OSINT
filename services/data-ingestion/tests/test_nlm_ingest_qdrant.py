from pathlib import Path
from types import SimpleNamespace

import pytest

from graph_integrity.spatial_normalizer import load_normalization_index
from nlm_ingest.ingest_qdrant import _point_id, build_claim_points
from nlm_ingest.schemas import Claim, Entity, Extraction
from spatial_catalog.identity import load_country_crosswalk

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CATALOG_DIRECTORY = (
    REPOSITORY_ROOT
    / "services/backend/data/spatial/catalogs/spatial-v1-e76a16bff799"
)
CROSSWALK_PATH = (
    REPOSITORY_ROOT
    / "services/data-ingestion/spatial_catalog/data/country_crosswalk.json"
)


@pytest.fixture(scope="module")
def spatial_index():
    return load_normalization_index(
        CATALOG_DIRECTORY,
        crosswalk_path=CROSSWALK_PATH,
    )


@pytest.fixture(scope="module")
def reviewed_geo_crosswalk():
    from qdrant_spatial import build_reviewed_country_name_crosswalk

    return build_reviewed_country_name_crosswalk(
        load_country_crosswalk(CROSSWALK_PATH)
    )


def _claim(stmt, conf=0.9):
    return Claim(statement=stmt, type="factual", polarity="positive",
                 entities_involved=["NATO"], confidence=conf, temporal_scope="2026")


def _extraction(**kw):
    base = dict(notebook_id="nb1", entities=[], relations=[],
                claims=[_claim("NATO expanded")],
                extraction_model="qwen", prompt_version="v1",
                source_kind="report", source_id="rep-a")
    base.update(kw)
    return Extraction(**base)


def test_point_id_is_source_specific_and_deterministic():
    a = _point_id("nb1", "report", "rep-a", "hash1")
    b = _point_id("nb1", "transcript", "transcript", "hash1")
    assert a == _point_id("nb1", "report", "rep-a", "hash1")   # deterministic
    assert a != b                                              # source-specific


def test_build_points_payload(monkeypatch):
    vectors = {"NATO expanded": [0.1] * 1024}
    points = build_claim_points(_extraction(), notebook_title="T",
                                embed=lambda text: vectors[text])
    assert len(points) == 1
    p = points[0].payload
    assert p["content"] == "NATO expanded"
    assert p["source_kind"] == "report" and p["source_id"] == "rep-a"
    assert p["region"] == "N/A"
    assert p["entities"] == [{"name": "NATO"}]
    assert "claim_hash" in p and "content_hash" in p and "ingested_at" in p


def test_rejected_claims_are_skipped():
    points = build_claim_points(_extraction(claims=[_claim("low", conf=0.0)]),
                                notebook_title="T", embed=lambda t: [0.0] * 1024)
    assert points == []


def test_claim_about_scope_requires_exact_typed_reviewed_entity(
    spatial_index,
    reviewed_geo_crosswalk,
):
    extraction = _extraction(
        entities=[
            Entity(
                name="Ukraine",
                type="COUNTRY",
                aliases=["UA"],
                confidence=0.91,
            )
        ],
        claims=[
            Claim(
                statement="Ukraine expanded air defence",
                type="factual",
                polarity="positive",
                entities_involved=["Ukraine"],
                confidence=0.9,
                temporal_scope="2026",
            )
        ],
    )

    point = build_claim_points(
        extraction,
        notebook_title="T",
        embed=lambda _text: [0.0] * 1024,
        spatial_index=spatial_index,
        reviewed_geo_crosswalk=reviewed_geo_crosswalk,
    )[0]

    assert point.payload["spatial_about_scope_revision_tokens"] == [
        "sr1|country:UKR|spatial-derive-v1-d30efa07e141"
    ]
    assert point.payload["spatial_occurrence_scope_revision_tokens"] == []
    audit = point.payload["spatial_derivations"][0]
    assert audit["confidence"] == 0.91
    assert audit["raw_location"]["source_country_name"] == "Ukraine"
    assert audit["crosswalk_status"] == "unique_reviewed"


def test_claim_text_and_extracted_alias_never_trigger_substring_geography(
    spatial_index,
    reviewed_geo_crosswalk,
):
    extraction = _extraction(
        entities=[
            Entity(
                name="Ukraine",
                type="COUNTRY",
                aliases=["UA"],
                confidence=0.99,
            )
        ],
        claims=[
            Claim(
                statement="Ukraine is discussed throughout this claim",
                type="factual",
                polarity="neutral",
                entities_involved=["Ukraine aid", "UA"],
                confidence=0.9,
                temporal_scope="2026",
            )
        ],
    )

    point = build_claim_points(
        extraction,
        notebook_title="T",
        embed=lambda _text: [0.0] * 1024,
        spatial_index=spatial_index,
        reviewed_geo_crosswalk=reviewed_geo_crosswalk,
    )[0]

    assert point.payload["spatial_about_scope_revision_tokens"] == []
    assert point.payload["spatial_derivations"] == []


def test_below_gate_about_entity_remains_audit_only(
    spatial_index,
    reviewed_geo_crosswalk,
):
    extraction = _extraction(
        entities=[
            Entity(
                name="Ukraine",
                type="COUNTRY",
                aliases=[],
                confidence=0.79,
            )
        ],
        claims=[
            Claim(
                statement="Ukraine is assessed",
                type="assessment",
                polarity="neutral",
                entities_involved=["Ukraine"],
                confidence=0.9,
                temporal_scope="2026",
            )
        ],
    )

    point = build_claim_points(
        extraction,
        notebook_title="T",
        embed=lambda _text: [0.0] * 1024,
        spatial_index=spatial_index,
        reviewed_geo_crosswalk=reviewed_geo_crosswalk,
    )[0]

    assert point.payload["spatial_about_scope_revision_tokens"] == []
    assert point.payload["spatial_derivation_status"] == "audit_only"
    assert point.payload["spatial_derivations"][0]["filter_reason"] == (
        "about_confidence_below_gate"
    )


@pytest.mark.asyncio
async def test_ensure_collection_creates_when_missing():
    import nlm_ingest.ingest_qdrant as iq
    created = {}

    class FakeQ:
        def get_collections(self):
            return SimpleNamespace(collections=[])

        def create_collection(self, collection_name, vectors_config):
            created.update(name=collection_name, size=vectors_config.size)

    await iq.ensure_collection(FakeQ(), "odin_intel", 1024)
    assert created == {"name": "odin_intel", "size": 1024}


@pytest.mark.asyncio
async def test_ensure_collection_validates_when_exists(monkeypatch):
    import nlm_ingest.ingest_qdrant as iq
    seen = {}

    class FakeQ:
        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name="odin_intel")])

        def get_collection(self, name):
            return {"name": name}

        def create_payload_index(self, *args, **kwargs):
            raise AssertionError("writer must not create payload indexes")

    monkeypatch.setattr(iq, "validate_collection_schema",
                        lambda info, enable_hybrid: seen.setdefault("validated", True))
    await iq.ensure_collection(FakeQ(), "odin_intel", 1024)
    assert seen["validated"] is True


@pytest.mark.asyncio
async def test_ensure_collection_aborts_on_schema_mismatch(monkeypatch):
    import nlm_ingest.ingest_qdrant as iq

    class FakeQ:
        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name="odin_intel")])

        def get_collection(self, name):
            return {}

    def _boom(info, enable_hybrid):
        raise RuntimeError("schema mismatch")

    monkeypatch.setattr(iq, "validate_collection_schema", _boom)
    with pytest.raises(RuntimeError, match="mismatch"):
        await iq.ensure_collection(FakeQ(), "odin_intel", 1024)


def test_claim_points_carry_notebooklm_provenance():
    from nlm_ingest.ingest_qdrant import build_claim_points
    extraction = _extraction(
        notebook_id="nb-7", source_kind="report", source_id="rpt-1",
        claims=[_claim("a claim", conf=0.9)],
    )
    points = build_claim_points(
        extraction, "Notebook Title", embed=lambda t: [0.0] * 1024,
        source_name="RAND",
    )
    p = points[0].payload
    assert p["source_type"] == "notebooklm"
    assert p["provider"] == "notebooklm:nb-7"
    assert p["display_name"] == "RAND"
    assert "credibility_score" not in p


@pytest.mark.asyncio
async def test_ensure_collection_aborts_in_hybrid_mode():
    import nlm_ingest.ingest_qdrant as iq

    class FakeQ:
        def get_collections(self):
            return SimpleNamespace(collections=[])

    with pytest.raises(NotImplementedError, match="dense-only"):
        await iq.ensure_collection(FakeQ(), "odin_intel", 1024, enable_hybrid=True)
