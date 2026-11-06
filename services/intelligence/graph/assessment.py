"""Read assessment values only at declared report field positions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, TypedDict

ASSESSMENT_NOTICE = (
    "Assessment-Felder konnten nicht eindeutig gelesen werden; "
    "angezeigte Standardwerte sind keine extrahierte Bewertung."
)
ASSESSMENT_FORMAT = (
    "Use exactly one 'Threat Assessment:' field with CRITICAL, HIGH, ELEVATED, MODERATE "
    "or NOT_ASSESSED when the evidence cannot support a current threat assessment, "
    "and exactly one 'Confidence Level:' field with high confidence, moderate confidence "
    "or low confidence (or 'not assessed' for no assessment). Put each value directly "
    "after its colon, or on the next line "
    "after a Markdown heading. Put explanations on separate lines."
)
_FIELD = re.compile(r"^(Threat Assessment|Confidence Level)\s*(?:(?:[:—–])\s*(.*))?$", re.I)
_THREAT = re.compile(
    r"^(CRITICAL|HIGH|ELEVATED|MODERATE|NOT_ASSESSED)(?:\s*$|\s*[—–:;,.(!]|\s+-\s+)", re.I
)
_CONFIDENCE = re.compile(
    r"^(high\s+confidence|moderate\s+confidence|low\s+confidence|not\s+assessed)"
    r"(?:\s*$|\s*[—–:;,.(!]|\s+-\s+)",
    re.I,
)


class AssessmentStatus(TypedDict):
    threat: Literal["declared", "default", "not_assessed"]
    confidence: Literal["declared", "default", "not_assessed"]
    issues: list[str]


@dataclass(frozen=True)
class AssessmentValues:
    threat: str | None
    confidence: float | None
    issues: tuple[str, ...]

    @property
    def status(self) -> AssessmentStatus:
        return {
            "threat": "not_assessed"
            if self.threat is None
            else "default"
            if any(issue.startswith("threat-") for issue in self.issues)
            else "declared",
            "confidence": "not_assessed"
            if self.confidence is None
            else "default"
            if any(issue.startswith("confidence-") for issue in self.issues)
            else "declared",
            "issues": list(self.issues),
        }


def _plain(line: str) -> str:
    text = line.strip().replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"^#{1,6}\s*", "", text)
    return re.sub(r"^\d+[.)]\s+", "", text).strip()


def parse_assessment(
    text: str, *, required: tuple[str, ...] = ("threat", "confidence")
) -> AssessmentValues:
    lines: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence is None:
            lines.append(_plain(line))

    fields: dict[str, list[str]] = {"threat": [], "confidence": []}
    for index, line in enumerate(lines):
        match = _FIELD.fullmatch(line)
        if match is None:
            continue
        key = "threat" if match[1].lower() == "threat assessment" else "confidence"
        value = match[2] or ""
        if not value:
            value = next((following for following in lines[index + 1 :] if following), "")
        fields[key].append(value.strip('"'))

    threat, confidence = "MODERATE", 0.5
    issues: list[str] = []
    for key in required:
        values = fields[key]
        if len(values) != 1:
            issues.append(f"{key}-{'missing' if not values else 'duplicate'}")
            continue
        match = (_THREAT if key == "threat" else _CONFIDENCE).match(values[0])
        if match is None:
            issues.append(f"{key}-invalid")
        elif key == "threat":
            threat = None if match[1].upper() == "NOT_ASSESSED" else match[1].upper()
        else:
            label = " ".join(match[1].lower().split())
            confidence = {
                "high confidence": 0.8,
                "moderate confidence": 0.6,
                "low confidence": 0.3,
                "not assessed": None,
            }[label]
    return AssessmentValues(threat, confidence, tuple(issues))


def annotate_assessment(text: str, values: AssessmentValues) -> str:
    if values.issues and ASSESSMENT_NOTICE not in text:
        return f"{text.rstrip()}\n\n{ASSESSMENT_NOTICE}"
    return text
