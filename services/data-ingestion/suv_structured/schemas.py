"""Pydantic model for one SUV defense-industry company + profile-text helper."""
from __future__ import annotations

from pydantic import BaseModel, field_validator


class Company(BaseModel):
    name: str
    suv_url: str
    aliases: list[str] = []
    hq_country: str | None = None   # raw SUV string (German), e.g. "Deutschland"
    hq_city: str | None = None
    employees: int | None = None
    revenue_eur: float | None = None
    founded: int | None = None      # year
    website: str | None = None      # absent on the directory page → stays None
    products: list[str] = []
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _name_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("company name must be non-empty")
        return v


def profile_text(c: Company) -> str:
    """Human-readable profile used as the Qdrant `content` (what gets embedded)."""
    parts = [f"{c.name} — Rüstungs-/Verteidigungsunternehmen."]
    loc = ", ".join(p for p in (c.hq_city, c.hq_country) if p)
    if loc:
        parts.append(f"Hauptsitz: {loc}.")
    if c.employees is not None:
        parts.append(f"Mitarbeiter: {c.employees}.")
    if c.revenue_eur is not None:
        parts.append(f"Umsatz: {c.revenue_eur:.0f} EUR.")
    if c.founded is not None:
        parts.append(f"Gegründet: {c.founded}.")
    if c.products:
        parts.append(f"Produkte: {', '.join(c.products)}.")
    if c.description:
        parts.append(c.description)
    return " ".join(parts)
