import json
from pathlib import Path

from nlm_ingest.cli import preview_relations


def _write_extraction(d: Path, nid: str, entities, relations):
    (d / "extractions").mkdir(parents=True, exist_ok=True)
    payload = {"notebook_id": nid, "entities": entities, "relations": relations, "claims": [],
               "extraction_model": "qwen", "prompt_version": "v4",
               "source_kind": "transcript", "source_id": "transcript"}
    (d / "extractions" / f"{nid}.transcript.json").write_text(json.dumps(payload))


def test_preview_counts(tmp_path):
    _write_extraction(tmp_path, "nb1",
        [{"name":"USA","type":"COUNTRY","aliases":[],"confidence":1.0},
         {"name":"Patriot","type":"WEAPON_SYSTEM","aliases":[],"confidence":1.0},
         {"name":"AI","type":"CONCEPT","aliases":[],"confidence":1.0}],
        [{"source":"USA","target":"Patriot","type":"OPERATES","evidence":"e","confidence":0.9},
         {"source":"USA","target":"AI","type":"OPERATES_IN","evidence":"e","confidence":0.9}])
    out = preview_relations(tmp_path)
    assert out["canonical_by_type"]["OPERATES"] == 1
    assert out["candidates_by_gate"]["OPERATES_IN.target_type"] == 1


def test_unknown_relation_type_survives_to_candidate(tmp_path):
    # spec §8: an unknown relation type must SURVIVE Extraction parsing (Relation.type
    # is str, not a Literal) so the validator classifies it as a structured candidate
    # (relation_type_unknown) instead of it being silently parse-dropped.
    (tmp_path / "extractions").mkdir(parents=True)
    payload = {"notebook_id": "nb1",
        "entities": [{"name": "A", "type": "COUNTRY", "aliases": [], "confidence": 1.0},
                     {"name": "B", "type": "COUNTRY", "aliases": [], "confidence": 1.0}],
        "relations": [{"source": "A", "target": "B", "type": "FROBNICATES",
                       "evidence": "e", "confidence": 0.9}],
        "claims": [], "extraction_model": "qwen", "prompt_version": "v4",
        "source_kind": "transcript", "source_id": "transcript"}
    (tmp_path / "extractions" / "nb1.transcript.json").write_text(json.dumps(payload))
    out = preview_relations(tmp_path)
    assert out["candidates_by_gate"]["relation_type_unknown"] == 1
