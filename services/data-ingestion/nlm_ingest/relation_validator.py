from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from canonicalize import canonicalize_entity
from nlm_ingest.ingest_neo4j import _canonical_name
from nlm_ingest.relation_rules import RELATION_ROLE_RULES

Endpoint = tuple[str, str]  # (name, type)


def normalize_evidence(s: str | None) -> str:
    return " ".join((s or "").split())


def canonical_pair(src: Endpoint, tgt: Endpoint, symmetric: bool) -> tuple[Endpoint, Endpoint]:
    if symmetric and tgt < src:
        return tgt, src
    return src, tgt


def relation_hash(src: Endpoint, type_: str, tgt: Endpoint, evidence: str | None) -> str:
    raw = "|".join([src[0], src[1], type_, tgt[0], tgt[1], normalize_evidence(evidence)])
    return hashlib.sha256(raw.encode()).hexdigest()


def provenance_key(notebook_id, source_kind, source_id, prompt_version,
                   extraction_model, rel_hash) -> str:
    return "|".join([notebook_id, source_kind, source_id, prompt_version,
                     extraction_model, rel_hash])


def candidate_id(prov_key: str, failed_gate: str) -> str:
    return hashlib.sha256(f"{prov_key}|{failed_gate}".encode()).hexdigest()


@dataclass
class CanonicalRelation:
    rel_type: str
    source: str
    source_type: str
    target: str
    target_type: str
    confidence: float
    evidence: str
    notebook_id: str
    source_kind: str
    source_id: str
    prompt_version: str
    extraction_model: str
    relation_hash: str
    provenance_key: str
    symmetric: bool


@dataclass
class CandidateRelation:
    candidate_id: str
    notebook_id: str
    source_kind: str
    source_id: str
    prompt_version: str
    extraction_model: str
    source: str
    source_type: str | None
    type: str
    target: str
    target_type: str | None
    evidence: str
    confidence: float
    failed_gate: str
    rejection_reason: str
    relation_hash: str
    status: str = "candidate"


@dataclass
class ValidationResult:
    canonical: list[CanonicalRelation] = field(default_factory=list)
    candidates: list[CandidateRelation] = field(default_factory=list)


def validate_relations(extraction) -> ValidationResult:
    # entity-type map keyed by the SAME normalization the write uses for endpoints.
    # Use the CANONICALIZED name+type so the map reflects the actual node written by
    # UPSERT_ENTITY (which runs canonicalize_entity before writing), not the declared
    # type. Without this, curated aliases (e.g. Royal Navy declared as ORGANIZATION
    # but written as MILITARY_UNIT) would cause the relation MATCH to find no node
    # and the edge would be silently dropped.
    type_map: dict[str, str] = {}
    for e in extraction.entities:
        canon = canonicalize_entity(e.name, e.type)
        type_map[canon.name] = canon.type

    res = ValidationResult()
    for r in extraction.relations:
        rtype = getattr(r, "type", None)
        src_name, tgt_name = r.source, r.target
        s_key, t_key = _canonical_name(src_name), _canonical_name(tgt_name)
        s_type, t_type = type_map.get(s_key), type_map.get(t_key)
        evidence = r.evidence or ""
        conf = float(getattr(r, "confidence", 0.0) or 0.0)

        def _candidate(gate: str, reason: str, *, s_key=s_key, s_type=s_type, t_key=t_key,
                       t_type=t_type, rtype=rtype, evidence=evidence,
                       conf=conf) -> CandidateRelation:
            rel_h = relation_hash((s_key, s_type or "?"), str(rtype),
                                  (t_key, t_type or "?"), evidence)
            pk = provenance_key(extraction.notebook_id, extraction.source_kind,
                                extraction.source_id, extraction.prompt_version,
                                extraction.extraction_model, rel_h)
            return CandidateRelation(
                candidate_id=candidate_id(pk, gate),
                notebook_id=extraction.notebook_id, source_kind=extraction.source_kind,
                source_id=extraction.source_id, prompt_version=extraction.prompt_version,
                extraction_model=extraction.extraction_model,
                source=s_key, source_type=s_type, type=str(rtype),
                target=t_key, target_type=t_type, evidence=evidence, confidence=conf,
                failed_gate=gate, rejection_reason=reason, relation_hash=rel_h,
            )

        rule = RELATION_ROLE_RULES.get(rtype)
        if rule is None:
            res.candidates.append(_candidate("relation_type_unknown",
                                             f"Unknown relation type: {rtype}"))
            continue
        if s_type is None or t_type is None:
            res.candidates.append(_candidate("entity_type_unresolved",
                                             f"Endpoint type unresolved: "
                                             f"{src_name if s_type is None else tgt_name}"))
            continue
        if rule.mode == "candidate_only":
            res.candidates.append(_candidate("relation_type_candidate_only",
                                             f"{rtype} is candidate-only in v2"))
            continue
        if s_type not in rule.source_types:
            res.candidates.append(_candidate(
                f"{rtype}.source_type",
                f"{rtype} requires source_type in {sorted(rule.source_types)}, got {s_type}"))
            continue
        if t_type not in rule.target_types:
            res.candidates.append(_candidate(
                f"{rtype}.target_type",
                f"{rtype} requires target_type in {sorted(rule.target_types)}, got {t_type}"))
            continue

        # valid -> canonical (symmetric sort on full (name,type) tuple before hashing)
        s_ep, t_ep = canonical_pair((s_key, s_type), (t_key, t_type), rule.symmetric)
        rel_h = relation_hash(s_ep, rtype, t_ep, evidence)
        pk = provenance_key(extraction.notebook_id, extraction.source_kind,
                            extraction.source_id, extraction.prompt_version,
                            extraction.extraction_model, rel_h)
        res.canonical.append(CanonicalRelation(
            rel_type=rtype, source=s_ep[0], source_type=s_ep[1],
            target=t_ep[0], target_type=t_ep[1], confidence=conf, evidence=evidence,
            notebook_id=extraction.notebook_id, source_kind=extraction.source_kind,
            source_id=extraction.source_id, prompt_version=extraction.prompt_version,
            extraction_model=extraction.extraction_model,
            relation_hash=rel_h, provenance_key=pk, symmetric=rule.symmetric))
    return res
