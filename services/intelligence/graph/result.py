"""Explicit non-success contracts shared by both workflow paths."""


class PipelineFailureError(RuntimeError):
    """An internal stage failed; public messages must not expose exception details."""


def insufficient_evidence() -> dict:
    return {
        "synthesis": "Für diese Anfrage liegen im vorliegenden Recherchelauf keine "
        "verwendbaren strukturierten Belege vor. Eine belastbare Antwort oder "
        "Bedrohungsbewertung ist damit nicht möglich. Dies ist keine Aussage "
        "über den gesamten Datenbestand.",
        "status": "completed",
        "answerability": "insufficient_evidence",
        "threat_assessment": None,
        "confidence": None,
        "assessment_status": {
            "threat": "not_assessed",
            "confidence": "not_assessed",
            "issues": ["no-consumed-evidence"],
        },
        "sources_used": [],
        "evidence_summary": [],
    }
