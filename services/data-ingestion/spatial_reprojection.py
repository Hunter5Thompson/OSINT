"""Re-normalize stored source evidence; never promote old derived tokens."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from graph_integrity.spatial_normalizer import (
    RawLocationIdentity,
    SpatialNormalizationIndex,
    normalize_location,
)
from qdrant_spatial import SpatialEvidenceV1, project_spatial_payload
from source_spatial import SOURCE_ID_FIELDS, project_feed_spatial


def reproject_payload(
    payload: Mapping[str, Any],
    index: SpatialNormalizationIndex,
) -> dict[str, Any]:
    """Build one complete replacement projection using source-owned raw evidence.

    Missing or malformed provenance withdraws admission. Operators can distinguish
    this from a geographic conflict and restore missing source evidence separately.
    """
    source = payload.get("source")
    if isinstance(source, str) and source in SOURCE_ID_FIELDS:
        result = project_feed_spatial(payload, index)
        if result.get("spatial_catalog_revision") == index.catalog_revision:
            return result
    evidence = []
    reason = "source evidence unavailable"
    supported = source == "gdelt_gkg" or payload.get("source_type") == "notebooklm"
    audits = payload.get("spatial_derivations") if supported else None
    if isinstance(audits, list):
        try:
            for audit in audits:
                if payload.get("source_type") == "notebooklm" and audit["relation"] != "about":
                    raise ValueError("NotebookLM evidence must remain about-only")
                if source == "gdelt_gkg" and (
                    not isinstance(payload.get("linked_event_ids"), list)
                    or audit["evidence_id"] not in payload["linked_event_ids"]
                    or audit["relation"] != "occurrence"
                ):
                    raise ValueError("GDELT evidence is not linked to this document")
                raw = RawLocationIdentity.model_validate_json(json.dumps(audit["raw_location"]))
                evidence.append(
                    SpatialEvidenceV1(
                        relation=audit["relation"],
                        evidence_kind=audit["evidence_kind"],
                        evidence_id=audit["evidence_id"],
                        confidence=audit["confidence"],
                        crosswalk_status=audit["crosswalk_status"],
                        normalization=normalize_location(raw, index),
                    )
                )
        except (KeyError, TypeError, ValueError):
            evidence = []
            reason = "stored source evidence is malformed or unlinked"
    result = project_spatial_payload(evidence, index)
    if not evidence:
        result["spatial_derivation_unavailable_reason"] = reason
    # Explicitly clear projection-owned geometry when no point is admitted.
    result.setdefault("geo", None)
    return result
