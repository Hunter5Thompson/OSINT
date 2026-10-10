"""Bounded synthetic analysis evaluation, separate from factual corpus release."""

from __future__ import annotations

import math
import statistics
from datetime import UTC, datetime

from graph.assessment import parse_assessment
from rag.corpus_policy import apply_tier_boost
from rag.evidence import (
    evidence_time_summary,
    neutralize_evidence_markers,
    pack_with_lineage,
    to_evidence_item,
)

HUMAN_DIMENSIONS = (
    "source_binding",
    "time_basis",
    "contradictions",
    "uncertainty",
    "utility",
    "injection_resistance",
)


def prepare_case(case: dict) -> tuple[str, list[dict], int]:
    """Use production score/decoder/pack functions; no Qdrant or corpus writes.

    Dataset fixtures deliberately bypass RSS/realtime lane selection. This is
    NOT a real retrieval-quality measurement; their fixed hits are the input.
    """
    hits = case["hits"]
    items = []
    for hit in apply_tier_boost(hits):
        clean = dict(hit)
        for key in ("title", "content"):
            if isinstance(clean.get(key), str):
                clean[key] = neutralize_evidence_markers(clean[key])
        try:
            items.append(to_evidence_item(clean))
        except (ValueError, TypeError, OverflowError):
            continue
    text, artifact = pack_with_lineage(items, budget=3000)
    rejected = len(hits) - len(items)
    if not text:
        text = "NO_VALID_RETRIEVAL_HITS" if rejected else "NO_SEMANTIC_MATCHES"
    return text, artifact, rejected


def _finite_nonnegative(value: object) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _load_accounted(run: dict, rows: list, expected: set[tuple[str, int]]) -> bool:
    """Validate supplied observation claims; the evaluator does not authenticate artifacts."""
    observations = run.get("load_observations")
    revision = run.get("model_revision")
    if (
        run.get("load_comparable") is not True
        or not isinstance(revision, str)
        or not revision.strip()
        or not _sha256(run.get("prompt_sha256"))
        or not isinstance(observations, list)
        or len(observations) != len(expected)
    ):
        return False
    indexed: dict[tuple[str, int], dict] = {}
    for row in rows:
        if (
            isinstance(row, dict)
            and isinstance(row.get("case_id"), str)
            and type(row.get("repetition")) is int
        ):
            indexed[(row["case_id"], row["repetition"])] = row
    seen: set[tuple[str, int]] = set()
    for observation in observations:
        if (
            not isinstance(observation, dict)
            or not isinstance(observation.get("case_id"), str)
            or type(observation.get("repetition")) is not int
        ):
            return False
        identity = (observation["case_id"], observation["repetition"])
        if identity not in expected or identity in seen or identity not in indexed:
            return False
        seen.add(identity)
        row = indexed[identity]
        start, finish, at = (
            _utc(row.get("started_at")),
            _utc(row.get("finished_at")),
            _utc(observation.get("observed_at")),
        )
        if (
            start is None
            or finish is None
            or at is None
            or not start <= at <= finish
            or observation.get("model_revision") != revision
            or observation.get("source") != "service-observation"
            or not _sha256(observation.get("evidence_sha256"))
            or type(observation.get("local_llm_count")) is not int
            or observation["local_llm_count"] != 1
            or type(observation.get("unrelated_generation_requests")) is not int
            or observation["unrelated_generation_requests"] != 0
        ):
            return False
    return seen == expected


def _human_metadata(review: dict) -> bool:
    for field in ("reviewer", "reviewed_at", "rationale"):
        value = review.get(field)
        if not isinstance(value, str) or not value.strip():
            return False
    try:
        datetime.fromisoformat(review["reviewed_at"])
    except ValueError:
        return False
    return review.get("review_method") == "human"


def evaluate_run(corpus: dict, corpus_sha256: str, run: dict) -> dict:
    """Fail missing/malformed accounting; never manufacture human acceptance."""
    errors: list[str] = []
    expected = {
        (case["case_id"], repetition)
        for case in corpus["cases"]
        for repetition in range(1, corpus["repetitions"] + 1)
    }
    cases = {case["case_id"]: case for case in corpus["cases"]}
    allowed = {
        key: {entry["source"]["source_ref_id"] for entry in prepare_case(case)[1]}
        for key, case in cases.items()
    }
    summaries = {key: evidence_time_summary(prepare_case(case)[1]) for key, case in cases.items()}
    if run.get("corpus_sha256") != corpus_sha256:
        errors.append("CORPUS_HASH_MISMATCH")
    rows = run.get("records")
    if not isinstance(rows, list):
        rows = []
        errors.append("INVALID_RECORDS_ROOT")
    seen: set[tuple[str, int]] = set()
    latencies: list[float] = []
    pending_reviews = 0
    failed_reviews = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"{index}:INVALID_RECORD")
            continue
        key, repetition = row.get("case_id"), row.get("repetition")
        if not isinstance(key, str) or type(repetition) is not int:
            errors.append(f"{index}:INVALID_CASE_ID")
            continue
        identity = (key, repetition)
        if identity not in expected or identity in seen:
            errors.append(f"{index}:UNEXPECTED_OR_DUPLICATE_CASE")
            continue
        seen.add(identity)
        analysis = row.get("analysis")
        if not isinstance(analysis, str) or not analysis.strip():
            errors.append(f"{key}:{repetition}:MISSING_ANALYSIS")
        else:
            parsed = parse_assessment(analysis)
            if row.get("assessment_status") != parsed.status:
                errors.append(f"{key}:{repetition}:ASSESSMENT_ORIGIN_MISMATCH")
            if (
                row.get("threat_assessment") != parsed.threat
                or row.get("confidence") != parsed.confidence
            ):
                errors.append(f"{key}:{repetition}:ASSESSMENT_VALUE_MISMATCH")
        if row.get("verification_status") != "unverified":
            errors.append(f"{key}:{repetition}:UNSUPPORTED_FACTUAL_STATUS")
        if row.get("evidence_summary") != summaries[key]:
            errors.append(f"{key}:{repetition}:EVIDENCE_TIME_METADATA_MISMATCH")
        if row.get("error_code") is not None:
            errors.append(f"{key}:{repetition}:RUNTIME_ERROR")
        refs = row.get("consumed_evidence_ref_ids")
        if (
            not isinstance(refs, list)
            or not all(isinstance(ref, str) for ref in refs)
            or len(refs) != len(set(refs))
            or set(refs) != allowed[key]
        ):
            errors.append(f"{key}:{repetition}:EVIDENCE_LINEAGE_MISMATCH")
        for name, gate in (("agent_turns", "max_agent_turns"), ("tool_starts", "max_tool_starts")):
            value = row.get(name)
            if type(value) is not int or not 0 <= value <= corpus["gates"][gate]:
                errors.append(f"{key}:{repetition}:INVALID_{name.upper()}")
        trace = row.get("tool_trace")
        if not isinstance(trace, list) or len(trace) != row.get("tool_starts"):
            errors.append(f"{key}:{repetition}:TOOL_START_TRACE_MISMATCH")
        elapsed = row.get("elapsed_seconds")
        if not _finite_nonnegative(elapsed):
            errors.append(f"{key}:{repetition}:INVALID_LATENCY")
        else:
            latencies.append(float(elapsed))
        review = row.get("human_review")
        if review is None:
            pending_reviews += 1
        elif not isinstance(review, dict):
            failed_reviews += 1
        else:
            ratings = review.get("ratings")
            valid_ratings = (
                isinstance(ratings, dict)
                and all(
                    type(ratings.get(dimension)) is int and ratings[dimension] in (1, 2)
                    for dimension in HUMAN_DIMENSIONS
                )
                and all(
                    ratings[dimension] == 2
                    for dimension in ("source_binding", "time_basis", "uncertainty")
                )
            )
            if (
                not valid_ratings
                or not _human_metadata(review)
                or review.get("critical_failures") != []
            ):
                failed_reviews += 1
    if seen != expected:
        errors.append("MISSING_CASE_REPETITIONS")
    comparable = _load_accounted(run, rows, expected)
    median = statistics.median(latencies) if latencies else None
    p95 = sorted(latencies)[math.ceil(len(latencies) * 0.95) - 1] if latencies else None
    if not comparable or len(latencies) != len(expected):
        latency_status = "UNKNOWN"
    else:
        latency_status = (
            "PASS"
            if (
                median <= corpus["gates"]["median_latency_seconds"]
                and p95 <= corpus["gates"]["nearest_rank_p95_seconds"]
            )
            else "FAIL"
        )
    human_status = (
        "FAIL" if failed_reviews else "PENDING" if (pending_reviews or seen != expected) else "PASS"
    )
    failed = bool(errors) or latency_status == "FAIL" or human_status == "FAIL"
    accepted = not errors and latency_status == "PASS" and human_status == "PASS"
    return {
        "schema_version": 1,
        "scope": corpus["scope"],
        "corpus_sha256": corpus_sha256,
        "status": "FAIL" if failed else "ACCEPTED" if accepted else "INCOMPLETE",
        "technical": {
            "status": "FAIL" if errors else "PASS",
            "errors": errors,
            "expected_records": len(expected),
            "accounted_records": len(seen),
        },
        "latency": {
            "status": latency_status,
            "median_seconds": median,
            "p95_seconds": p95,
            "load_comparable": comparable,
        },
        "human": {
            "status": human_status,
            "pending": pending_reviews,
            "failed": failed_reviews,
            "provided_claims_only": True,
        },
        "factual_release": False,
        "release_gate": "OPEN",
    }
