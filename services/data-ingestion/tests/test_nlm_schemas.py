import pytest
from pydantic import ValidationError

from nlm_ingest.schemas import (
    Claim,
    Entity,
    Extraction,
    Relation,
    Transcript,
    TranscriptSegment,
    claim_hash,
)


class TestTranscriptSegment:
    def test_basic(self):
        seg = TranscriptSegment(start=0.0, end=5.3, text="Hello world")
        assert seg.speaker is None
        assert seg.text == "Hello world"

    def test_with_speaker(self):
        seg = TranscriptSegment(start=0.0, end=5.3, speaker="Host", text="Hello")
        assert seg.speaker == "Host"


class TestTranscript:
    def test_requires_notebook_id(self):
        t = Transcript(
            notebook_id="abc123",
            duration_seconds=600.0,
            language="en",
            segments=[],
            full_text="",
        )
        assert t.notebook_id == "abc123"

    def test_missing_notebook_id_raises(self):
        with pytest.raises(ValidationError):
            Transcript(
                duration_seconds=600.0,
                language="en",
                segments=[],
                full_text="",
            )


class TestEntity:
    def test_valid_type(self):
        e = Entity(name="NATO", type="ORGANIZATION", confidence=0.9)
        assert e.aliases == []

    def test_invalid_type_raises(self):
        with pytest.raises(ValidationError):
            Entity(name="NATO", type="INVALID_TYPE", confidence=0.9)


class TestRelation:
    def test_basic(self):
        r = Relation(
            source="USA", target="China",
            type="COMPETES_WITH",
            evidence="trade tensions",
            confidence=0.85,
        )
        assert r.type == "COMPETES_WITH"

    def test_invalid_relation_type_raises(self):
        with pytest.raises(ValidationError):
            Relation(
                source="A", target="B",
                type="LOVES",
                evidence="x",
                confidence=0.5,
            )


class TestClaim:
    def test_basic(self):
        c = Claim(
            statement="China will invade Taiwan by 2027",
            type="prediction",
            polarity="negative",
            entities_involved=["China", "Taiwan"],
            confidence=0.6,
            temporal_scope="2027",
        )
        assert c.type == "prediction"

    def test_invalid_claim_type_raises(self):
        with pytest.raises(ValidationError):
            Claim(
                statement="x", type="opinion", polarity="neutral",
                entities_involved=[], confidence=0.5, temporal_scope="",
            )


class TestExtraction:
    def test_basic(self):
        ext = Extraction(
            notebook_id="nb1",
            entities=[],
            relations=[],
            claims=[],
            extraction_model="qwen3.5",
            prompt_version="v1",
        )
        assert ext.extraction_model == "qwen3.5"


class TestClaimHash:
    def test_deterministic(self):
        h1 = claim_hash("China will invade Taiwan by 2027")
        h2 = claim_hash("China will invade Taiwan by 2027")
        assert h1 == h2

    def test_length_24_hex(self):
        h = claim_hash("test statement")
        assert len(h) == 24
        assert all(c in "0123456789abcdef" for c in h)

    def test_case_insensitive(self):
        h1 = claim_hash("NATO expands eastward")
        h2 = claim_hash("nato expands eastward")
        assert h1 == h2

    def test_whitespace_normalized(self):
        h1 = claim_hash("China   will  invade")
        h2 = claim_hash("China will invade")
        assert h1 == h2

    def test_punctuation_ignored(self):
        h1 = claim_hash("China will invade Taiwan.")
        h2 = claim_hash("China will invade Taiwan")
        assert h1 == h2

    def test_unicode_normalized(self):
        h1 = claim_hash("deﬁnition")
        h2 = claim_hash("definition")
        assert h1 == h2

    def test_different_statements_differ(self):
        h1 = claim_hash("China invades Taiwan")
        h2 = claim_hash("Russia invades Ukraine")
        assert h1 != h2
