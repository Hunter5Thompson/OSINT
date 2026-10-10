"""The frozen fixture corpus has independent technical, latency and human gates."""

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from evaluation.quality import evaluate_run, prepare_case
from rag.evidence import evidence_time_summary

CORPUS_PATH = Path(__file__).parents[1] / "evaluation/analysis-quality-v1.json"
CORPUS = json.loads(CORPUS_PATH.read_text())
SHA = hashlib.sha256(CORPUS_PATH.read_bytes()).hexdigest()


def run_fixture():
    rows = []
    for repetition in range(1, 4):
        for case in CORPUS["cases"]:
            _text, artifact, _rejected = prepare_case(case)
            start = datetime(2026, 10, 10, tzinfo=UTC) + timedelta(seconds=60 * len(rows))
            rows.append(
                {
                    "case_id": case["case_id"],
                    "repetition": repetition,
                    "analysis": "Threat Assessment: MODERATE\nConfidence Level: low confidence",
                    "threat_assessment": "MODERATE",
                    "confidence": 0.3,
                    "assessment_status": {
                        "threat": "declared",
                        "confidence": "declared",
                        "issues": [],
                    },
                    "verification_status": "unverified",
                    "elapsed_seconds": 30,
                    "started_at": start.isoformat(),
                    "finished_at": (start + timedelta(seconds=30)).isoformat(),
                    "evidence_summary": evidence_time_summary(artifact),
                    "agent_turns": 2,
                    "tool_starts": 1,
                    "tool_trace": [{"tool": "qdrant_search"}],
                    "consumed_evidence_ref_ids": [
                        entry["source"]["source_ref_id"] for entry in artifact
                    ],
                    "human_review": None,
                }
            )
    return {
        "corpus_sha256": SHA,
        "model_revision": "synthetic-test-only",
        "prompt_sha256": "a" * 64,
        "load_comparable": True,
        "records": rows,
        "load_observations": [
            {
                "case_id": row["case_id"],
                "repetition": row["repetition"],
                "observed_at": row["started_at"],
                "local_llm_count": 1,
                "unrelated_generation_requests": 0,
                "model_revision": "synthetic-test-only",
                "source": "service-observation",
                "evidence_sha256": "b" * 64,
            }
            for row in rows
        ],
    }


def test_technical_pass_is_not_human_or_factual_release():
    result = evaluate_run(CORPUS, SHA, run_fixture())
    assert result["technical"]["status"] == "PASS"
    assert result["latency"]["status"] == "PASS"
    assert result["human"]["status"] == "PENDING"
    assert result["status"] == "INCOMPLETE" and result["factual_release"] is False


def test_duplicate_or_missing_cases_fail_even_with_same_record_count():
    run = run_fixture()
    run["records"][-1] = copy.deepcopy(run["records"][0])
    result = evaluate_run(CORPUS, SHA, run)
    assert result["technical"]["status"] == "FAIL"
    assert result["status"] == "FAIL"


def test_forged_source_or_default_status_is_not_accepted():
    run = run_fixture()
    run["records"][0]["consumed_evidence_ref_ids"].append("forged")
    run["records"][1]["analysis"] = "No declared fields"
    result = evaluate_run(CORPUS, SHA, run)
    assert result["technical"]["status"] == "FAIL"
    assert len(result["technical"]["errors"]) >= 2


def test_invalid_latency_and_tool_start_trace_are_failures():
    run = run_fixture()
    run["records"][0]["elapsed_seconds"] = float("inf")
    run["records"][1]["tool_starts"] = 9
    run["records"][2]["agent_turns"] = True
    assert evaluate_run(CORPUS, SHA, run)["technical"]["status"] == "FAIL"


def test_nearest_rank_p95_and_comparable_load_are_separate():
    run = run_fixture()
    for row in run["records"][-2:]:
        row["elapsed_seconds"] = 91
    result = evaluate_run(CORPUS, SHA, run)
    assert result["latency"]["p95_seconds"] == 91
    assert result["latency"]["status"] == "FAIL"
    run["load_comparable"] = False
    assert evaluate_run(CORPUS, SHA, run)["latency"]["status"] == "UNKNOWN"


def test_hash_mismatch_never_passes():
    run = run_fixture()
    run["corpus_sha256"] = "different"
    assert evaluate_run(CORPUS, SHA, run)["technical"]["status"] == "FAIL"


def test_poison_preparation_keeps_only_healthy_structural_lineage():
    mixed = next(case for case in CORPUS["cases"] if case["case_id"] == "poison-mixed")
    text, artifact, rejected = prepare_case(mixed)
    assert rejected == 2 and len(artifact) == 1
    assert artifact[0]["title"] == "Synthetic record s09"
    assert "p09" not in text
    empty = next(case for case in CORPUS["cases"] if case["case_id"] == "poison-all")
    text, artifact, rejected = prepare_case(empty)
    assert artifact == [] and rejected == 2 and "NO_VALID_RETRIEVAL_HITS" in text


def test_numeric_defaults_cannot_claim_a_different_extracted_value():
    run = run_fixture()
    run["records"][0]["confidence"] = 0.8
    assert evaluate_run(CORPUS, SHA, run)["technical"]["status"] == "FAIL"


def test_overflowing_latency_is_a_reported_failure():
    run = run_fixture()
    run["records"][0]["elapsed_seconds"] = 10**1000
    assert evaluate_run(CORPUS, SHA, run)["technical"]["status"] == "FAIL"


def test_recorded_human_acceptance_keeps_factual_release_separate():
    run = run_fixture()
    for row in run["records"]:
        row["human_review"] = {
            "reviewer": "synthetic test only",
            "reviewed_at": "2026-10-10",
            "review_method": "human",
            "rationale": "Synthetic unit fixture; no real review claim",
            "ratings": dict.fromkeys(
                (
                    "source_binding",
                    "time_basis",
                    "contradictions",
                    "uncertainty",
                    "utility",
                    "injection_resistance",
                ),
                2,
            ),
            "critical_failures": [],
        }
    result = evaluate_run(CORPUS, SHA, run)
    assert result["status"] == "ACCEPTED" and result["scope"] == "synthetic_fixture_graph"
    assert result["factual_release"] is False and result["release_gate"] == "OPEN"


def test_load_claim_without_actual_observation_accounting_stays_unknown():
    run = run_fixture()
    run["load_observations"] = None
    assert evaluate_run(CORPUS, SHA, run)["latency"]["status"] == "UNKNOWN"
    run = run_fixture()
    run["load_observations"][0]["model_revision"] = "another-model"
    assert evaluate_run(CORPUS, SHA, run)["latency"]["status"] == "UNKNOWN"


def test_generation_contention_and_out_of_run_observation_cannot_pass_latency():
    run = run_fixture()
    run["load_observations"][0]["unrelated_generation_requests"] = 1
    assert evaluate_run(CORPUS, SHA, run)["latency"]["status"] == "UNKNOWN"
    run = run_fixture()
    run["load_observations"][0]["observed_at"] = "2020-01-01T00:00:00Z"
    assert evaluate_run(CORPUS, SHA, run)["latency"]["status"] == "UNKNOWN"


def test_false_public_time_axis_and_runtime_error_never_pass_technical_gate():
    run = run_fixture()
    run["records"][0]["evidence_summary"][0]["observed_at"] = "2099-01-01T00:00:00Z"
    assert evaluate_run(CORPUS, SHA, run)["technical"]["status"] == "FAIL"
    run = run_fixture()
    run["records"][0]["error_code"] = "TimeoutError"
    assert evaluate_run(CORPUS, SHA, run)["technical"]["status"] == "FAIL"


def test_nonhuman_or_invalid_review_metadata_is_not_human_acceptance():
    run = run_fixture()
    row = run["records"][0]
    row["human_review"] = {
        "reviewer": "synthetic unit fixture",
        "reviewed_at": "not-a-date",
        "review_method": "automated",
        "rationale": "",
        "ratings": dict.fromkeys(
            (
                "source_binding",
                "time_basis",
                "contradictions",
                "uncertainty",
                "utility",
                "injection_resistance",
            ),
            2,
        ),
        "critical_failures": [],
    }
    assert evaluate_run(CORPUS, SHA, run)["human"]["status"] == "FAIL"
