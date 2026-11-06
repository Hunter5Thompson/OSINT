"""Immutable, allowlisted NotebookLM archive: build once, search without writes.

The public interface is build_catalog(packages, destination) and
NotebookResearch.search(question). Callers never resolve paths or choose stores.
Original passages remain attributed source content, not reviewed factual claims.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from functools import lru_cache
from pathlib import Path

import httpx

from config import settings
from rag.evidence import EvidenceItem, NotebookPassage, SourceRef

EmbedBatch = Callable[[list[str]], Awaitable[list[list[float]]]]
EmbedQuery = Callable[[str], Awaitable[list[float]]]
NOTEBOOK_EVIDENCE_MAX_CHARS = 14000


async def embed_notebook_documents(texts: list[str]) -> list[list[float]]:
    """Owned TEI adapter: fail explicitly instead of losing a corpus batch."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        info = await client.get(f"{settings.tei_embed_url}/info")
        info.raise_for_status()
        if info.json().get("model_id") != settings.notebook_embedding_model:
            raise ValueError("TEI embedding model mismatch")
        response = await client.post(f"{settings.tei_embed_url}/embed", json={"inputs": texts})
        response.raise_for_status()
        vectors = response.json()
    if len(vectors) != len(texts):
        raise ValueError("TEI embedding batch incomplete")
    return [_unit(vector) for vector in vectors]


async def embed_notebook_query(question: str) -> list[float]:
    # Qwen's query instruction is deliberately absent from indexed documents.
    query = "Instruct: Given a question, retrieve relevant source passages that answer it.\nQuery: "
    return (await embed_notebook_documents([query + question]))[0]


@lru_cache(maxsize=2)
def _configured_research(path: Path, sha256: str, model: str) -> NotebookResearch:
    if not sha256:
        raise ValueError("configured notebook catalog requires SHA-256")
    return NotebookResearch(
        path, expected_sha256=sha256, embedding_model=model, embed_query=embed_notebook_query
    )


async def notebook_context(question: str) -> list[EvidenceItem]:
    if settings.notebook_catalog_path is None:
        return []
    return await asyncio.wait_for(
        _configured_research(
            settings.notebook_catalog_path,
            settings.notebook_catalog_sha256,
            settings.notebook_embedding_model,
        ).search(question),
        timeout=20.0,
    )


async def notebook_readiness() -> dict:
    if settings.notebook_catalog_path is None:
        return {"enabled": False}
    research = _configured_research(
        settings.notebook_catalog_path,
        settings.notebook_catalog_sha256,
        settings.notebook_embedding_model,
    )
    return await asyncio.to_thread(research.info)


def _hash(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _unit(vector: list[float]) -> list[float]:
    if not vector or not all(math.isfinite(value) for value in vector):
        raise ValueError("invalid embedding vector")
    norm = math.sqrt(math.fsum(value * value for value in vector))
    if norm == 0:
        raise ValueError("zero embedding vector")
    return [value / norm for value in vector]


def _passages(content: str):
    start = 0
    while start < len(content):
        end = min(start + 1600, len(content))
        if end < len(content):
            boundary = content.rfind(" ", start + 1200, end)
            if boundary > start:
                end = boundary
        yield start, end, content[start:end]
        if end == len(content):
            break
        start = end - 240


async def build_catalog(
    packages: Mapping[str, Path], destination: Path, *, embed: EmbedBatch, embedding_model: str
) -> dict:
    """Build a new archive from selected source packages; never edit originals."""
    if destination.exists():
        raise FileExistsError(destination)
    items = []
    for domain, root in packages.items():
        if domain not in {"intel", "methods"}:
            raise ValueError("unknown knowledge domain")
        manifest = (root / "manifest.json").read_bytes()
        manifest_hash = _hash(manifest)
        sealed = {entry["path"]: entry["sha256"] for entry in json.loads(manifest)["files"]}
        for name in ("curated-claims.jsonl", "evidence-register.json", "import-scope.json"):
            if _hash((root / name).read_bytes()) != sealed.get(name):
                raise ValueError("package hash mismatch: " + name)
        evidence = {r["id"]: r for r in json.loads((root / "evidence-register.json").read_text())}
        scope = json.loads((root / "import-scope.json").read_text())
        allowed = {r["candidate_id"]: r for r in scope["candidate_allowlist"]}
        held = set(scope["held_claim_ids"]) | set(scope["excluded_claim_ids"])
        for line in (root / "curated-claims.jsonl").read_text().splitlines():
            row = json.loads(line)
            permit = allowed.get(row["candidate_id"], {})
            if (
                permit.get("statement_sha256") != _hash(row["statement"])
                or permit.get("notebook_id") != row["notebook_id"]
                or row["candidate_id"] in held
                or row["claim_id"] in held
                or row["original_source_id"] in scope["deny_original_source_ids"]
                or row["knowledge_domain"] != domain
            ):
                raise ValueError("candidate outside allowed scope")
            anchor = row["source_anchor"]
            raw = Path(anchor["path"]).read_bytes()
            if _hash(raw) != anchor["sha256"]:
                raise ValueError("original source file hash mismatch")
            source = json.loads(raw)
            if _hash(source["content"]) != anchor["content_sha256"]:
                raise ValueError("original source text hash mismatch")
            original = evidence[row["evidence_ids"][0]]
            lineage = original["independent_lineage"]
            for start, end, text in _passages(source["content"]):
                identity = f"{domain}:{anchor['content_sha256']}:{start}:{end}"
                items.append(
                    EvidenceItem(
                        evidence_id="ev-" + _hash(identity)[:24],
                        knowledge_role="method" if domain == "methods" else "background",
                        title=original["title"],
                        excerpt=text,
                        relevance_score=0,
                        content_hash=_hash(text),
                        source=SourceRef(
                            source_ref_id=_hash(lineage)[:16],
                            source_type="notebooklm",
                            provider="notebooklm:" + row["notebook_id"],
                            url=original.get("url"),
                            credibility_score=0.6,
                        ),
                        passage=NotebookPassage(
                            notebook_id=row["notebook_id"],
                            original_source_id=row["original_source_id"],
                            source_sha256=anchor["sha256"],
                            text_sha256=anchor["content_sha256"],
                            start=start,
                            end=end,
                            passage_sha256=_hash(text),
                            independent_lineage=lineage,
                            package_sha256=manifest_hash,
                            parent_candidate_id=row["candidate_id"],
                            qualification_note=row["qualification"],
                            unresolved_checks=row.get("unresolved_checks", []),
                            source_date_context=row.get("source_date_context"),
                        ),
                    )
                )
    vectors = []
    for offset in range(0, len(items), 16):
        batch = items[offset : offset + 16]
        vectors.extend(
            _unit(v) for v in await embed([item.title + "\n" + item.excerpt for item in batch])
        )
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".sqlite") as temporary:
        with sqlite3.connect(temporary.name) as db:
            db.execute("CREATE TABLE metadata (model TEXT)")
            db.execute("INSERT INTO metadata VALUES (?)", (embedding_model,))
            db.execute("CREATE TABLE passages (item TEXT, vector TEXT)")
            db.executemany(
                "INSERT INTO passages VALUES (?, ?)",
                [
                    (item.model_dump_json(), json.dumps(vector))
                    for item, vector in zip(items, vectors, strict=True)
                ],
            )
        # Atomic publication, including an explicit no-overwrite guarantee.
        os.link(temporary.name, destination)
    return {"passages": len(items), "embedding_model": embedding_model}


class NotebookResearch:
    """Read-only archive search. Empty matches and unavailable retrieval differ."""

    def __init__(
        self,
        path: Path,
        *,
        embed_query: EmbedQuery,
        embedding_model: str,
        expected_sha256: str | None = None,
    ):
        self.path = path
        self.embed_query = embed_query
        self.embedding_model = embedding_model
        self.expected_sha256 = expected_sha256
        self._rows: list[tuple[EvidenceItem, list[float]]] | None = None

    def _load(self) -> list[tuple[EvidenceItem, list[float]]]:
        if self.expected_sha256 and _hash(self.path.read_bytes()) != self.expected_sha256:
            raise ValueError("catalog hash mismatch")
        with sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            if db.execute("SELECT model FROM metadata").fetchone()[0] != self.embedding_model:
                raise ValueError("catalog embedding model mismatch")
            rows = db.execute("SELECT item, vector FROM passages").fetchall()
        return [
            (EvidenceItem.model_validate_json(raw), _unit(json.loads(vector)))
            for raw, vector in rows
        ]

    def info(self) -> dict:
        """Validate the pinned archive and report technical coverage for readiness."""
        if self._rows is None:
            self._rows = self._load()
        return {
            "enabled": True,
            "sha256": self.expected_sha256,
            "passages": len(self._rows),
            "sources": len(
                {item.passage.original_source_id for item, _ in self._rows if item.passage}
            ),
        }

    async def search(self, question: str) -> list[EvidenceItem]:
        if not question.strip():
            return []
        if self._rows is None:
            self._rows = await asyncio.to_thread(self._load)
        query = _unit(await self.embed_query(question))
        return await asyncio.to_thread(self._select, query)

    def _select(self, query: list[float]) -> list[EvidenceItem]:
        scored = []
        for item, values in self._rows or []:
            score = math.fsum(a * b for a, b in zip(query, values, strict=True))
            if score >= 0.45:
                scored.append(item.model_copy(update={"relevance_score": score}))
        selected = []
        for role, limit in (("background", 3), ("method", 1)):
            origins: Counter[str] = Counter()
            for item in sorted(scored, key=lambda item: item.relevance_score, reverse=True):
                if item.knowledge_role != role or origins[item.source.source_ref_id] >= 2:
                    continue
                if sum(origins.values()) == limit:
                    break
                window = self._context_window(item)
                if any(
                    previous.knowledge_role == window.knowledge_role
                    and previous.passage.text_sha256 == window.passage.text_sha256
                    and previous.passage.start < window.passage.end
                    and window.passage.start < previous.passage.end
                    for previous in selected
                ):
                    continue
                selected.append(window)
                origins[item.source.source_ref_id] += 1
        background = [item for item in selected if item.knowledge_role == "background"]
        methods = [item for item in selected if item.knowledge_role == "method"]
        return background[:1] + methods + background[1:]

    def _context_window(self, item: EvidenceItem) -> EvidenceItem:
        """Keep one neighbour on each side so quoted views retain their rebuttal.

        Windows are reconstructed only from sealed, overlapping source slices.
        The returned identity/hash/range describes exactly the expanded text.
        """
        rows = sorted(
            (row for row, _ in self._rows or []
             if row.passage.parent_candidate_id == item.passage.parent_candidate_id),
            key=lambda row: row.passage.start,
        )
        index = next(i for i, row in enumerate(rows) if row.evidence_id == item.evidence_id)
        neighbours = rows[max(0, index - 1):index + 2]
        text, end = neighbours[0].excerpt, neighbours[0].passage.end
        for neighbour in neighbours[1:]:
            overlap = end - neighbour.passage.start
            if overlap <= 0 or text[-overlap:] != neighbour.excerpt[:overlap]:
                raise ValueError("inconsistent notebook passage overlap")
            text += neighbour.excerpt[overlap:]
            end = neighbour.passage.end
        start = neighbours[0].passage.start
        domain = "methods" if item.knowledge_role == "method" else "intel"
        identity = f"{domain}:{item.passage.text_sha256}:{start}:{end}"
        passage = item.passage.model_copy(update={
            "start": start, "end": end, "passage_sha256": _hash(text),
        })
        return item.model_copy(update={
            "evidence_id": "ev-" + _hash(identity)[:24], "excerpt": text,
            "content_hash": _hash(text), "passage": passage,
        })
