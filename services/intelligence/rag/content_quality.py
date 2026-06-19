"""Content-quality heuristic: is a corpus chunk usable analysis prose, or junk
(empty / base64 data-URI blob / keyword-soup with no sentence structure)?

Used by the intelligence READ-PATH guard (rag/corpus_policy.validate_lane) to drop
junk chunks from retrieval. A twin lives at
services/data-ingestion/feeds/content_quality.py for the ingest-guard — KEEP THE TWO
COPIES IN SYNC (tests in both services assert the same cases). NotebookLM
single-sentence claims are deliberately treated as usable prose.
"""
from __future__ import annotations

import re

# data:<mime>;base64,<blob> — embedded images/files that bloat content and poison embeddings.
_DATA_URI = re.compile(r"data:[^,\s]*;base64,[A-Za-z0-9+/=]+")

MIN_CHARS = 40          # below this (after stripping data-URIs) = not a usable chunk
MIN_WORDS = 8           # a real claim/sentence has at least this many words
MAX_DATA_URI_FRAC = 0.25  # data-URI blobs may not dominate the content
LOW_PROSE_MIN_CHARS = 200  # long text with zero sentence punctuation = keyword soup


def strip_data_uris(text: str) -> str:
    """Remove embedded base64 data-URI blobs (e.g. data:image/png;base64,....)."""
    return _DATA_URI.sub("", text or "")


def content_junk_reason(text: str) -> str | None:
    """Return a short junk reason, or None if the text is usable analysis prose.

    Passes legitimate short prose such as NotebookLM single-sentence claims
    (>= MIN_CHARS, >= MIN_WORDS, with sentence punctuation). Flags: empty,
    base64-image-heavy, too-short, too-few-words, and long keyword-soup (no sentences).
    """
    raw = text or ""
    n_raw = len(raw.strip())
    if n_raw == 0:
        return "empty"
    data_uri_chars = sum(len(m) for m in _DATA_URI.findall(raw))
    if data_uri_chars / n_raw > MAX_DATA_URI_FRAC:
        return "base64_heavy"
    prose = strip_data_uris(raw).strip()
    if len(prose) < MIN_CHARS:
        return "too_short"
    if len(prose.split()) < MIN_WORDS:
        return "too_few_words"
    # "Structure" = sentence/clause punctuation OR a line break. Only a long single run
    # with NONE of these is keyword-soup junk; bullet lists, German ;:-prose, and a
    # mid-sentence chunker cut are legitimate and stay (avoids false positives).
    has_structure = any(ch in prose for ch in ".!?;:") or "\n" in prose
    if len(prose) >= LOW_PROSE_MIN_CHARS and not has_structure:
        return "low_prose"
    return None
