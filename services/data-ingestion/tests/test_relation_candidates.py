import json

from nlm_ingest.candidates import write_candidates
from nlm_ingest.relation_validator import CandidateRelation


def _cand(cid):
    return CandidateRelation(
        candidate_id=cid,
        notebook_id="nb1",
        source_kind="transcript",
        source_id="transcript",
        prompt_version="v4",
        extraction_model="qwen",
        source="Germany",
        source_type="COUNTRY",
        type="OPERATES_IN",
        target="F-127",
        target_type="VESSEL",
        evidence="ev",
        confidence=0.9,
        failed_gate="OPERATES_IN.target_type",
        rejection_reason="...",
        relation_hash="h",
    )


def test_write_is_idempotent_and_dedupes(tmp_path):
    p = tmp_path / "rc.jsonl"
    n1 = write_candidates(
        p, [_cand("a"), _cand("a"), _cand("b")], "2026-06-20T00:00:00Z"
    )
    first = p.read_text()
    n2 = write_candidates(p, [_cand("b"), _cand("a")], "2026-06-20T00:00:00Z")
    assert n1 == 2 and n2 == 2
    assert p.read_text() == first  # same content regardless of order/dupes
    lines = [json.loads(x) for x in p.read_text().splitlines()]
    assert {line["candidate_id"] for line in lines} == {"a", "b"}
