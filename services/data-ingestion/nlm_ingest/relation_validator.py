from __future__ import annotations

import hashlib

Endpoint = tuple[str, str]  # (name, type)


def normalize_evidence(s: str | None) -> str:
    return " ".join((s or "").split())


def canonical_pair(src: Endpoint, tgt: Endpoint, symmetric: bool) -> tuple[Endpoint, Endpoint]:
    if symmetric and tgt < src:
        return tgt, src
    return src, tgt


def relation_hash(src: Endpoint, type_: str, tgt: Endpoint, evidence: str | None) -> str:
    raw = "|".join([src[0], src[1], type_, tgt[0], tgt[1], normalize_evidence(evidence)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def provenance_key(notebook_id, source_kind, source_id, prompt_version,
                   extraction_model, rel_hash) -> str:
    return "|".join([notebook_id, source_kind, source_id, prompt_version,
                     extraction_model, rel_hash])


def candidate_id(prov_key: str, failed_gate: str) -> str:
    return hashlib.sha256(f"{prov_key}|{failed_gate}".encode("utf-8")).hexdigest()
