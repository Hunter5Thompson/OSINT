"""Structure-aware markdown chunking. Splits at heading→paragraph→sentence
boundaries, accumulates to ~target_tokens (char-approx), with token overlap.
No blind fixed-window (keeps nav/footnote noise from cross-cutting chunks).
No hard cap on single-segment size: a paragraph with no .!? terminators
(URL lines, table rows) emits as one segment and may exceed target_tokens."""
from __future__ import annotations

import re

_CHARS_PER_TOKEN = 4
_SENT = re.compile(r"(?<=[.!?])\s+")
_HEADING = re.compile(r"^#{1,6}\s+")


def _segments(md: str) -> list[str]:
    """Heading-leading paragraphs, then sentences for over-long paragraphs."""
    segs: list[str] = []
    for para in re.split(r"\n\s*\n", md.strip()):
        p = para.strip()
        if not p:
            continue
        p = _HEADING.sub("", p).replace("\n", " ")
        segs.extend(s.strip() for s in _SENT.split(p) if s.strip())
    return segs


def chunk_markdown(md: str, *, target_tokens: int = 650, overlap_tokens: int = 100) -> list[str]:
    target = target_tokens * _CHARS_PER_TOKEN
    overlap = overlap_tokens * _CHARS_PER_TOKEN
    segs = _segments(md)
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for seg in segs:
        if cur and cur_len + len(seg) + 1 > target:
            chunks.append(" ".join(cur).strip())
            # overlap: carry trailing segments up to ~overlap chars into next chunk
            carry: list[str] = []
            carry_len = 0
            for s in reversed(cur):
                if carry_len + len(s) > overlap:
                    break
                carry.insert(0, s)
                carry_len += len(s) + 1
            cur = carry
            cur_len = carry_len
        cur.append(seg)
        cur_len += len(seg) + 1
    if cur:
        chunks.append(" ".join(cur).strip())
    return [c for c in chunks if c]
