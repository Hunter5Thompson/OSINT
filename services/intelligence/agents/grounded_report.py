"""Bounded citation validation for reports consuming original archive passages.

The draft gets one source-check/revision pass. Deterministic checks establish
citation identity, not entailment or external factual truth.
"""

import re
from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage

from graph.assessment import parse_assessment
from graph.result import PipelineFailureError

_IDENTITY = re.compile(r"(?<![\w-])ev-[\w-]+")
_CITATION = re.compile(r"\[(ev-[\w-]+)\]|`(ev-[\w-]+)`|(?<![\w-])(ev-[\w-]+)")


async def compose_report(
    messages: Sequence[BaseMessage],
    evidence_ids: set[str],
    model: BaseChatModel,
    *,
    background_only: bool = False,
) -> str:
    conversation = list(messages)
    if background_only:
        conversation.append(
            HumanMessage(
                content=(
                    "Dieser Lauf enthält nur Archivhintergrund und Methoden. Schreibe eine "
                    "zugeschriebene Einordnung, keine aktuelle Ereignisbestätigung. Pflichtfelder: "
                    "Threat Assessment: NOT_ASSESSED\nConfidence Level: not assessed"
                )
            )
        )
    for _attempt in range(2):
        # Reserve the revision's allowance for the actual report. Otherwise the
        # deployed Qwen server can spend it entirely on reasoning and return "".
        response = (
            await model.ainvoke(
                conversation, extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                max_tokens=2000,
            )
            if _attempt else await model.ainvoke(conversation)
        )
        text = response.content if isinstance(response.content, str) else ""
        # Accept formatting differences, never approximate an evidence identity.
        cited = set(_IDENTITY.findall(text))
        assessment = parse_assessment(text)
        allowed_assessment = not background_only or (
            assessment.threat is None and assessment.confidence is None
        )
        if (
            _attempt == 1 and text.strip() and cited
            and cited <= evidence_ids and allowed_assessment
            and response.response_metadata.get("finish_reason") != "length"
        ):
            return _CITATION.sub(
                lambda match: "[" + next(g for g in match.groups() if g) + "]", text
            )
        conversation.extend(
            [
                response,
                HumanMessage(
                    content=(
                        "Prüfe den Entwurf Satz für Satz gegen die Originalpassagen oben und "
                        "gib ausschließlich den korrigierten vollständigen Bericht zurück. "
                        "Besonders wichtig: Unterscheide die Position des Autors von einer "
                        "fremden Position, die er zitiert und anschließend bestreitet. Lies "
                        "Negationen und Widersprüche bis zum Ende der Passage. Schreibe dem "
                        "Autor keine von ihm zurückgewiesene Position zu. Prüfe Datierungen: "
                        "Alte Nachrichten sind keine aktuell geltenden Vereinbarungen; "
                        "unbekannte Daten bleiben unbekannt. Belege jeden sachlichen Absatz "
                        "mit den vorliegenden [ev-...] IDs. Erfinde keine IDs oder Fakten. "
                        "Entferne unbelegte Paraphrasen, statt sie als Hypothese zu tarnen. "
                        "Beachte die vorgegebene Bewertungsgrenze. Erkläre Prüfgrenzen in "
                        "normalem Deutsch, ohne technische Feldnamen oder Quellen-Scores. "
                        "Zulässige IDs: "
                        + ", ".join(sorted(evidence_ids))
                    )
                ),
            ]
        )
    raise PipelineFailureError("Report citation validation failed")
