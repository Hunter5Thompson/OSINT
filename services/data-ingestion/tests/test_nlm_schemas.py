import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from nlm_ingest.schemas import (
    CANONICAL_ENTITY_TYPES,
    LEGACY_ENTITY_TYPE_MAP,
    Claim,
    Entity,
    Extraction,
    Relation,
    Transcript,
    TranscriptSegment,
    claim_hash,
    normalize_entity_type,
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

    def test_schema_accepts_LOCATION(self):
        """LOCATION is a canonical EntityType and validates without error."""
        e = Entity(name="Berlin", type="LOCATION", confidence=0.9)
        assert e.type == "LOCATION"


_CANONICAL_TYPES = (
    "AIRCRAFT",
    "CONCEPT",
    "COUNTRY",
    "LOCATION",
    "MILITARY_UNIT",
    "ORGANIZATION",
    "PERSON",
    "POLICY",
    "REGION",
    "SATELLITE",
    "TREATY",
    "VESSEL",
    "WEAPON_SYSTEM",
)


_LEGACY_PAIRS = (
    ("person", "PERSON"),
    ("organization", "ORGANIZATION"),
    ("location", "LOCATION"),
    ("military_unit", "MILITARY_UNIT"),
    ("weapon_system", "WEAPON_SYSTEM"),
    ("vessel", "VESSEL"),
    ("aircraft", "AIRCRAFT"),
    ("satellite", "SATELLITE"),
)


class TestEntityTypeNormalizer:
    def test_canonical_set_has_13_entries(self):
        assert len(CANONICAL_ENTITY_TYPES) == 13
        assert set(CANONICAL_ENTITY_TYPES) == set(_CANONICAL_TYPES)

    def test_legacy_map_has_exactly_8_entries(self):
        assert len(LEGACY_ENTITY_TYPE_MAP) == 8
        assert dict(LEGACY_ENTITY_TYPE_MAP) == dict(_LEGACY_PAIRS)

    @pytest.mark.parametrize("canonical", _CANONICAL_TYPES)
    def test_normalizer_idempotent_on_canonical(self, canonical):
        assert normalize_entity_type(canonical) == canonical

    @pytest.mark.parametrize("lower,upper", _LEGACY_PAIRS)
    def test_normalizer_maps_legacy(self, lower, upper):
        assert normalize_entity_type(lower) == upper

    def test_normalizer_raises_on_unknown(self):
        with pytest.raises(ValueError) as exc_info:
            normalize_entity_type("garbage")
        assert "garbage" in str(exc_info.value)

    def test_legacy_map_covers_intelligence_extractor_literal(self):
        """Drift guard: LEGACY_ENTITY_TYPE_MAP keys must equal the lowercase
        Literal values on intelligence/codebook/extractor.py:ExtractedEntityRaw.type.

        Cross-build-context Python import is impossible (data-ingestion and
        intelligence have separate Docker contexts), so this test parses the
        intelligence file as text. If the intelligence file is missing
        (stripped container), skip rather than fail.
        """
        # tests/ → data-ingestion/ → services/ ; intelligence service lives next to data-ingestion.
        extractor_path = (
            Path(__file__).resolve().parents[2] / "intelligence" / "codebook" / "extractor.py"
        )
        if not extractor_path.exists():
            pytest.skip(f"intelligence extractor not present at {extractor_path}")

        source = extractor_path.read_text()

        # Locate the ExtractedEntityRaw class and grab its `type: Literal[...]` block.
        class_match = re.search(
            r"class\s+ExtractedEntityRaw\b.*?(?=\nclass\s|\Z)",
            source,
            flags=re.DOTALL,
        )
        assert class_match, "ExtractedEntityRaw class not found in intelligence extractor.py"
        class_body = class_match.group(0)

        literal_match = re.search(
            r"type\s*:\s*Literal\[(.*?)\]",
            class_body,
            flags=re.DOTALL,
        )
        assert literal_match, (
            "Could not locate `type: Literal[...]` in ExtractedEntityRaw — "
            "drift test cannot verify"
        )

        literal_block = literal_match.group(1)
        # Extract every quoted string ("...") inside the Literal[...] block.
        extracted_values = set(re.findall(r'"([^"]+)"', literal_block))
        assert extracted_values, (
            "No quoted entity-type values parsed from intelligence extractor.py — "
            "regex needs review"
        )

        legacy_keys = set(LEGACY_ENTITY_TYPE_MAP.keys())
        missing = extracted_values - legacy_keys
        extra = legacy_keys - extracted_values
        assert extracted_values == legacy_keys, (
            "Drift between data-ingestion LEGACY_ENTITY_TYPE_MAP and "
            "intelligence/codebook/extractor.py ExtractedEntityRaw.type Literal. "
            f"In intelligence but not in legacy map: {sorted(missing)}. "
            f"In legacy map but not in intelligence: {sorted(extra)}."
        )


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
