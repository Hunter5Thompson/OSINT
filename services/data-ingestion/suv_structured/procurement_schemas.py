"""Pydantic model for one SUV Modernisierungsvorhaben (procurement program) + profile text."""
from __future__ import annotations

from pydantic import BaseModel, field_validator


class ProcurementProgram(BaseModel):
    title: str                          # the ### heading; unique key for node
    branch: str                         # Teilstreitkraft section
    typ: str | None = None              # Typ
    status: str | None = None           # Projektstatus
    contractor_raw: str | None = None   # Auftragnehmer verbatim (always retained)
    quantity: int | None = None         # parsed Stückzahl
    quantity_raw: str | None = None
    cost_eur: float | None = None       # parsed Kosten (EUR)
    cost_raw: str | None = None
    financing: str | None = None        # Finanzierung
    delivery_start: int | None = None   # parsed from Auslieferung
    delivery_end: int | None = None
    delivery_raw: str | None = None
    description: str | None = None       # Beschreibung
    suv_url: str

    @field_validator("title")
    @classmethod
    def _title_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("program title must be non-empty")
        return v


def profile_text(p: ProcurementProgram) -> str:
    """Human-readable profile used as the Qdrant `content` (what gets embedded)."""
    parts = [f"{p.title} — Bundeswehr-Modernisierungsvorhaben"]
    if p.typ:
        parts[0] += f" ({p.typ})"
    parts[0] += "."
    if p.status:
        parts.append(f"Projektstatus: {p.status}.")
    if p.quantity is not None:
        parts.append(f"Stückzahl: {p.quantity}.")
    if p.cost_eur is not None:
        parts.append(f"Kosten: {p.cost_eur:.0f} EUR.")
    if p.financing:
        parts.append(f"Finanzierung: {p.financing}.")
    if p.delivery_raw:
        parts.append(f"Auslieferung: {p.delivery_raw}.")
    if p.contractor_raw:
        parts.append(f"Auftragnehmer: {p.contractor_raw}.")
    if p.description:
        parts.append(p.description)
    return " ".join(parts)
