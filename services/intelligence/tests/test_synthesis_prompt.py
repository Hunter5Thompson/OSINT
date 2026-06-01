from agents.synthesis_agent import SYSTEM_PROMPT


def test_prompt_explains_evidence_semantics():
    p = SYSTEM_PROMPT.lower()
    assert "credibility_score" in p
    assert "verlässlichkeit" in p          # reliability, not truth
    assert "provenance_inferred" in p
    assert "published_at" in p
    assert "ingested_at" in p
