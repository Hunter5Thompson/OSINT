from types import SimpleNamespace

import pytest

from nlm_ingest.ingest_qdrant import _point_id, build_claim_points
from nlm_ingest.schemas import Claim, Extraction


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


@pytest.mark.asyncio
async def test_ensure_collection_aborts_in_hybrid_mode():
    import nlm_ingest.ingest_qdrant as iq

    class FakeQ:
        def get_collections(self):
            return SimpleNamespace(collections=[])

    with pytest.raises(NotImplementedError, match="dense-only"):
        await iq.ensure_collection(FakeQ(), "odin_intel", 1024, enable_hybrid=True)
