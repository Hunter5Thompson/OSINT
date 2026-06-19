"""Content-quality heuristic (ingest-guard side). Mirror of the intelligence twin —
services/intelligence/tests/test_content_quality.py asserts the same cases."""
from feeds.content_quality import content_junk_reason, strip_data_uris

# A real NotebookLM single-sentence claim — MUST be treated as usable prose.
NLM_CLAIM = (
    "There is a resurgence of defense technology investment in Silicon Valley "
    "driven by geopolitical competition with China."
)
PROSE = (
    "Modern military hardware production, including semiconductors and aluminum, is more "
    "energy-intensive than historical heavy industry like WWII shipbuilding."
)


class TestContentJunkReason:
    def test_empty(self):
        assert content_junk_reason("") == "empty"
        assert content_junk_reason("   \n  ") == "empty"
        assert content_junk_reason(None) == "empty"

    def test_base64_heavy(self):
        text = "Some title " + "data:image/png;base64," + "A" * 5000
        assert content_junk_reason(text) == "base64_heavy"

    def test_too_short(self):
        assert content_junk_reason("Short bit.") == "too_short"

    def test_too_few_words(self):
        # >= MIN_CHARS but < MIN_WORDS (padded single long token)
        assert content_junk_reason("x" * 60 + " yz") == "too_few_words"

    def test_low_prose_keyword_soup(self):
        soup = " ".join(["EU-Cybersicherheit", "Militärische", "Cyberfähigkeit"] * 20)
        assert len(soup) >= 200 and "." not in soup
        assert content_junk_reason(soup) == "low_prose"

    def test_valid_prose_passes(self):
        assert content_junk_reason(PROSE) is None

    def test_nlm_single_sentence_claim_passes(self):
        assert content_junk_reason(NLM_CLAIM) is None

    def test_prose_with_inline_image_still_passes(self):
        # A normal article that happens to embed one small image is not junk.
        text = PROSE + " data:image/png;base64,AAAA " + PROSE
        assert content_junk_reason(text) is None

    def test_bullet_list_passes(self):
        # markdown bullet list (newlines) is legitimate structure, not keyword-soup
        bullets = "\n".join(f"- Item {i} on defense procurement and logistics" for i in range(8))
        assert content_junk_reason(bullets) is None


class TestStripDataUris:
    def test_removes_base64_blob(self):
        out = strip_data_uris("before data:image/png;base64,iVBORw0KGgoAAAA after")
        assert "base64" not in out
        assert "before" in out and "after" in out
