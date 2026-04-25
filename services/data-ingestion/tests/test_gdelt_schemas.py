import pytest
from pydantic import ValidationError

from gdelt_raw.schemas import GDELTDocumentWrite, GDELTEventWrite


def _valid_event() -> dict:
    return {
        "event_id": "gdelt:event:1300904663",
        "cameo_code": "193", "cameo_root": 19, "quad_class": 4,
        "goldstein": -6.5, "avg_tone": -4.2,
        "num_mentions": 12, "num_sources": 8, "num_articles": 11,
        "date_added": "2026-04-25T12:15:00Z", "fraction_date": 2026.3164,
        "actor1_code": "MIL", "actor1_name": "MILITARY",
        "actor2_code": "REB", "actor2_name": "REBELS",
        "source_url": "https://example.com/x",
        "codebook_type": "conflict.armed",
        "source": "gdelt",
        "filter_reason": "tactical",
    }


def _valid_doc() -> dict:
    return {
        "doc_id": "gdelt:gkg:20260425121500-42",
        "url": "https://example.com/a",
        "source_name": "reuters.com",
        "gdelt_date": "2026-04-25T12:15:00Z",
        "published_at": None,
        "themes": ["ARMEDCONFLICT"],
        "persons": [], "organizations": [],
        "tone_polarity": 8.4, "word_count": 599,
        "source": "gdelt_gkg",
    }


def test_event_valid():
    GDELTEventWrite(**_valid_event())


def test_event_rejects_missing_event_id():
    d = _valid_event(); del d["event_id"]
    with pytest.raises(ValidationError):
        GDELTEventWrite(**d)


def test_event_rejects_wrong_event_id_pattern():
    d = _valid_event(); d["event_id"] = "not-canonical"
    with pytest.raises(ValidationError):
        GDELTEventWrite(**d)


def test_event_rejects_unknown_fields():
    d = _valid_event(); d["rogue_field"] = "x"
    with pytest.raises(ValidationError):
        GDELTEventWrite(**d)


def test_doc_valid():
    GDELTDocumentWrite(**_valid_doc())


def test_doc_rejects_missing_doc_id():
    d = _valid_doc(); del d["doc_id"]
    with pytest.raises(ValidationError):
        GDELTDocumentWrite(**d)


def test_doc_rejects_wrong_doc_id_pattern():
    d = _valid_doc(); d["doc_id"] = "gkg-20260425121500-42"
    with pytest.raises(ValidationError):
        GDELTDocumentWrite(**d)


def test_doc_published_at_is_optional():
    d = _valid_doc(); d["published_at"] = None
    GDELTDocumentWrite(**d)
