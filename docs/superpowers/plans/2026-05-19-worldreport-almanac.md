# WorldReport Almanac Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first WorldReport Almanac slice inside the existing Worldview country Inspector.

**Architecture:** Add a small FastAPI Almanac router backed by a static JSON country file and deterministic signal matching over the existing signal stream. Add typed frontend API helpers, a `useCountryAlmanac` hook, and a `CountryAlmanacPanel` that replaces the current S2.5 placeholder in `CountryHeader`.

**Tech Stack:** FastAPI, Pydantic v2, pytest, React, TypeScript strict, Vitest, React Testing Library.

---

## File Structure

Backend:

- Create `services/backend/app/models/almanac.py`: Pydantic response models for facts and compact signal items.
- Create `services/backend/app/services/country_almanac.py`: JSON loader, ID normalization, lookup, and signal matching.
- Create `services/backend/app/routers/almanac.py`: `/almanac/countries/{country_id}` and `/almanac/countries/{country_id}/signals`.
- Create `services/backend/data/country_almanac.json`: sparse country fact seed covering the countries needed by current tests and enough global examples to prove the shape. Generated enrichment can expand it later.
- Modify `services/backend/app/main.py`: mount Almanac router under `/api`.
- Test `services/backend/tests/test_country_almanac_service.py`.
- Test `services/backend/tests/test_almanac_router.py`.

Frontend:

- Create `services/frontend/src/types/almanac.ts`: typed country fact and signal contracts.
- Modify `services/frontend/src/services/api.ts`: `getCountryAlmanac()` and `getCountryAlmanacSignals()`.
- Create `services/frontend/src/hooks/useCountryAlmanac.ts`: independent facts/signals fetch state.
- Create `services/frontend/src/components/globe/spotlight/CountryAlmanacPanel.tsx`: render facts, empty/error states, signals, and capability strip.
- Modify `services/frontend/src/components/globe/spotlight/CountryHeader.tsx`: replace placeholder with panel.
- Modify `services/frontend/src/components/worldview/worldviewHudLoader.css`: Almanac panel styles.
- Update `services/frontend/src/components/globe/spotlight/__tests__/CountryHeader.test.tsx`.

## Task 1: Backend Models and Static Service

**Files:**

- Create: `services/backend/app/models/almanac.py`
- Create: `services/backend/app/services/country_almanac.py`
- Create: `services/backend/data/country_almanac.json`
- Test: `services/backend/tests/test_country_almanac_service.py`

- [ ] **Step 1: Write the failing service tests**

Create `services/backend/tests/test_country_almanac_service.py`:

```python
import json
from pathlib import Path

from app.models.signals import SignalEnvelope, SignalPayload
from app.services.country_almanac import CountryAlmanacStore


def _write_data(tmp_path: Path) -> Path:
    data = {
        "countries": [
            {
                "id": "GRC",
                "iso3": "GRC",
                "m49": "300",
                "name": "Greece",
                "region": "Europe",
                "subregion": "Southern Europe",
                "capital": {"name": "Athens", "lat": 37.98, "lon": 23.73},
                "facts": {
                    "profile": [{"label": "Area", "value": "131,957 sq km"}],
                    "people": [{"label": "Population", "value": "10.4M"}],
                    "government": [],
                    "economy": [],
                    "security": [],
                },
                "updated_at": "2026-05-19",
                "source_note": "test",
            },
            {
                "id": "732",
                "iso3": None,
                "m49": "732",
                "name": "W. Sahara",
                "region": "Africa",
                "subregion": "Northern Africa",
                "capital": None,
                "facts": {"profile": [], "people": [], "government": [], "economy": [], "security": []},
                "updated_at": "2026-05-19",
                "source_note": "test",
            },
        ]
    }
    p = tmp_path / "country_almanac.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _signal(**payload: object) -> SignalEnvelope:
    return SignalEnvelope(
        event_id="0001768651200000-000001",
        ts="2026-05-19T10:20:00.000Z",
        type="signal.rss",
        payload=SignalPayload(redis_id="1-0", **payload),
    )


def test_lookup_resolves_iso3_case_insensitively(tmp_path: Path) -> None:
    store = CountryAlmanacStore(_write_data(tmp_path))
    country = store.get_country("grc")
    assert country.name == "Greece"
    assert country.capital is not None
    assert country.capital.name == "Athens"


def test_lookup_resolves_m49_fallback(tmp_path: Path) -> None:
    store = CountryAlmanacStore(_write_data(tmp_path))
    country = store.get_country("732")
    assert country.name == "W. Sahara"
    assert country.iso3 is None


def test_lookup_returns_none_for_unknown(tmp_path: Path) -> None:
    store = CountryAlmanacStore(_write_data(tmp_path))
    assert store.get_country("missing") is None


def test_signal_matching_prefers_explicit_iso3(tmp_path: Path) -> None:
    store = CountryAlmanacStore(_write_data(tmp_path))
    matches = store.match_signals("GRC", [_signal(title="irrelevant", country_iso3="grc")])
    assert [item.event_id for item in matches] == ["0001768651200000-000001"]
    assert matches[0].title == "irrelevant"


def test_signal_matching_allows_exact_country_name_field(tmp_path: Path) -> None:
    store = CountryAlmanacStore(_write_data(tmp_path))
    matches = store.match_signals("GRC", [_signal(title="Athens update", country_name="Greece")])
    assert len(matches) == 1


def test_signal_matching_rejects_title_substring(tmp_path: Path) -> None:
    store = CountryAlmanacStore(_write_data(tmp_path))
    matches = store.match_signals("GRC", [_signal(title="Greece mentioned in title")])
    assert matches == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd services/backend && uv run pytest tests/test_country_almanac_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.country_almanac'`.

- [ ] **Step 3: Create Pydantic models**

Create `services/backend/app/models/almanac.py`:

```python
"""Models for the WorldReport country Almanac."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AlmanacCapital(BaseModel):
    name: str
    lat: float
    lon: float


class AlmanacFact(BaseModel):
    label: str
    value: str


class AlmanacFacts(BaseModel):
    profile: list[AlmanacFact] = Field(default_factory=list)
    people: list[AlmanacFact] = Field(default_factory=list)
    government: list[AlmanacFact] = Field(default_factory=list)
    economy: list[AlmanacFact] = Field(default_factory=list)
    security: list[AlmanacFact] = Field(default_factory=list)


class CountryAlmanac(BaseModel):
    id: str
    iso3: str | None = None
    m49: str
    name: str
    region: str = ""
    subregion: str = ""
    capital: AlmanacCapital | None = None
    facts: AlmanacFacts = Field(default_factory=AlmanacFacts)
    updated_at: str
    source_note: str


class AlmanacSignalItem(BaseModel):
    event_id: str
    ts: str
    type: str
    title: str
    severity: str
    source: str
    url: str = ""


class AlmanacSignalResponse(BaseModel):
    country_id: str
    items: list[AlmanacSignalItem]
```

- [ ] **Step 4: Create the static seed JSON**

Create `services/backend/data/country_almanac.json` with this initial shape:

```json
{
  "countries": [
    {
      "id": "GRC",
      "iso3": "GRC",
      "m49": "300",
      "name": "Greece",
      "region": "Europe",
      "subregion": "Southern Europe",
      "capital": { "name": "Athens", "lat": 37.98, "lon": 23.73 },
      "facts": {
        "profile": [
          { "label": "Area", "value": "131,957 sq km" },
          { "label": "Currency", "value": "Euro (EUR)" }
        ],
        "people": [
          { "label": "Population", "value": "10.4M" },
          { "label": "Languages", "value": "Greek" }
        ],
        "government": [
          { "label": "Government type", "value": "Parliamentary republic" }
        ],
        "economy": [
          { "label": "Economic note", "value": "Service and shipping-heavy EU economy" }
        ],
        "security": [
          { "label": "Security note", "value": "NATO member; Eastern Mediterranean posture" }
        ]
      },
      "updated_at": "2026-05-19",
      "source_note": "ODIN static country almanac"
    },
    {
      "id": "USA",
      "iso3": "USA",
      "m49": "840",
      "name": "United States of America",
      "region": "Americas",
      "subregion": "Northern America",
      "capital": { "name": "Washington, D.C.", "lat": 38.9, "lon": -77.04 },
      "facts": {
        "profile": [
          { "label": "Currency", "value": "US dollar (USD)" }
        ],
        "people": [
          { "label": "Languages", "value": "English, Spanish and others" }
        ],
        "government": [
          { "label": "Government type", "value": "Federal presidential constitutional republic" }
        ],
        "economy": [],
        "security": [
          { "label": "Security note", "value": "NATO member; global force projection" }
        ]
      },
      "updated_at": "2026-05-19",
      "source_note": "ODIN static country almanac"
    },
    {
      "id": "732",
      "iso3": null,
      "m49": "732",
      "name": "W. Sahara",
      "region": "Africa",
      "subregion": "Northern Africa",
      "capital": null,
      "facts": {
        "profile": [
          { "label": "Status", "value": "Disputed territory in current map dataset" }
        ],
        "people": [],
        "government": [],
        "economy": [],
        "security": []
      },
      "updated_at": "2026-05-19",
      "source_note": "ODIN static country almanac"
    }
  ]
}
```

- [ ] **Step 5: Implement the service**

Create `services/backend/app/services/country_almanac.py`:

```python
"""Static country Almanac loader and deterministic signal matching."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models.almanac import AlmanacSignalItem, CountryAlmanac
from app.models.signals import SignalEnvelope


DEFAULT_ALMANAC_PATH = Path(__file__).resolve().parents[2] / "data" / "country_almanac.json"


class CountryAlmanacStore:
    def __init__(self, path: Path = DEFAULT_ALMANAC_PATH) -> None:
        self.path = path
        self._by_id: dict[str, CountryAlmanac] | None = None

    def get_country(self, country_id: str) -> CountryAlmanac | None:
        self._ensure_loaded()
        assert self._by_id is not None
        return self._by_id.get(_norm_id(country_id))

    def match_signals(
        self,
        country_id: str,
        envelopes: list[SignalEnvelope],
        limit: int = 5,
    ) -> list[AlmanacSignalItem]:
        country = self.get_country(country_id)
        if country is None:
            return []
        matches: list[AlmanacSignalItem] = []
        for envelope in envelopes:
            if _matches_country(country, envelope):
                matches.append(_signal_item(envelope))
            if len(matches) >= limit:
                break
        return matches

    def _ensure_loaded(self) -> None:
        if self._by_id is not None:
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        by_id: dict[str, CountryAlmanac] = {}
        for item in raw.get("countries", []):
            country = CountryAlmanac.model_validate(item)
            by_id[_norm_id(country.id)] = country
            by_id[_norm_id(country.m49)] = country
            if country.iso3:
                by_id[_norm_id(country.iso3)] = country
        self._by_id = by_id


def get_country_almanac_store() -> CountryAlmanacStore:
    return CountryAlmanacStore()


def _norm_id(value: str) -> str:
    return value.strip().upper()


def _norm_name(value: object) -> str:
    return " ".join(str(value).strip().casefold().split())


def _payload_extra(envelope: SignalEnvelope) -> dict[str, Any]:
    return envelope.payload.model_extra or {}


def _payload_value(envelope: SignalEnvelope, key: str) -> object:
    if hasattr(envelope.payload, key):
        return getattr(envelope.payload, key)
    return _payload_extra(envelope).get(key)


def _matches_country(country: CountryAlmanac, envelope: SignalEnvelope) -> bool:
    iso_fields = ("iso3", "country_iso3", "country_code")
    if country.iso3:
        target_iso = _norm_id(country.iso3)
        for field in iso_fields:
            value = _payload_value(envelope, field)
            if isinstance(value, str) and _norm_id(value) == target_iso:
                return True

    for field in ("m49", "country_m49"):
        value = _payload_value(envelope, field)
        if isinstance(value, str | int) and str(value).strip() == country.m49:
            return True

    target_name = _norm_name(country.name)
    for field in ("country", "country_name", "location_country"):
        value = _payload_value(envelope, field)
        if isinstance(value, str) and _norm_name(value) == target_name:
            return True
    return False


def _signal_item(envelope: SignalEnvelope) -> AlmanacSignalItem:
    return AlmanacSignalItem(
        event_id=envelope.event_id,
        ts=envelope.ts,
        type=envelope.type,
        title=envelope.payload.title,
        severity=envelope.payload.severity,
        source=envelope.payload.source,
        url=envelope.payload.url,
    )
```

- [ ] **Step 6: Run service tests**

Run:

```bash
cd services/backend && uv run pytest tests/test_country_almanac_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit backend service**

```bash
git add services/backend/app/models/almanac.py services/backend/app/services/country_almanac.py services/backend/data/country_almanac.json services/backend/tests/test_country_almanac_service.py
git commit -m "feat(backend): add country almanac service"
```

## Task 2: Backend Almanac Router

**Files:**

- Create: `services/backend/app/routers/almanac.py`
- Modify: `services/backend/app/main.py`
- Test: `services/backend/tests/test_almanac_router.py`

- [ ] **Step 1: Write failing router tests**

Create `services/backend/tests/test_almanac_router.py`:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.signals import SignalEnvelope, SignalPayload
from app.routers import almanac
from app.services.signal_stream import get_signal_stream


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(almanac.router, prefix="/api")
    return app


def test_get_country_almanac_by_iso3() -> None:
    client = TestClient(_build_app())
    response = client.get("/api/almanac/countries/GRC")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Greece"
    assert body["capital"]["name"] == "Athens"


def test_get_country_almanac_by_m49() -> None:
    client = TestClient(_build_app())
    response = client.get("/api/almanac/countries/732")
    assert response.status_code == 200
    assert response.json()["name"] == "W. Sahara"


def test_get_country_almanac_404_for_unknown() -> None:
    client = TestClient(_build_app())
    response = client.get("/api/almanac/countries/NOPE")
    assert response.status_code == 404
    assert response.json()["detail"] == "country almanac not found"


def test_get_country_signals_matches_explicit_iso3() -> None:
    stream = get_signal_stream()
    stream.clear_for_tests()
    stream.add_for_tests(
        SignalEnvelope(
            event_id="0001768651200000-000001",
            ts="2026-05-19T10:20:00.000Z",
            type="signal.rss",
            payload=SignalPayload(
                redis_id="1-0",
                title="Diplomatic statement indexed by Hugin",
                severity="low",
                source="rss",
                country_iso3="GRC",
            ),
        )
    )

    client = TestClient(_build_app())
    response = client.get("/api/almanac/countries/GRC/signals?limit=5")
    assert response.status_code == 200
    body = response.json()
    assert body["country_id"] == "GRC"
    assert body["items"][0]["title"] == "Diplomatic statement indexed by Hugin"


def test_get_country_signals_rejects_title_only_match() -> None:
    stream = get_signal_stream()
    stream.clear_for_tests()
    stream.add_for_tests(
        SignalEnvelope(
            event_id="0001768651200000-000002",
            ts="2026-05-19T10:21:00.000Z",
            type="signal.rss",
            payload=SignalPayload(
                redis_id="2-0",
                title="Greece mentioned only in title",
                severity="low",
                source="rss",
            ),
        )
    )

    client = TestClient(_build_app())
    response = client.get("/api/almanac/countries/GRC/signals?limit=5")
    assert response.status_code == 200
    assert response.json()["items"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd services/backend && uv run pytest tests/test_almanac_router.py -q
```

Expected: FAIL with import error for `app.routers.almanac` or missing test helpers on `SignalStream`.

- [ ] **Step 3: Add test helpers to signal stream if absent**

If `services/backend/app/services/signal_stream.py` does not already have deterministic test helpers, add:

```python
    def clear_for_tests(self) -> None:
        self._buffer.clear()

    def add_for_tests(self, envelope: SignalEnvelope) -> None:
        self._buffer.append(envelope)
```

- [ ] **Step 4: Implement router**

Create `services/backend/app/routers/almanac.py`:

```python
"""WorldReport Almanac endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.models.almanac import AlmanacSignalResponse, CountryAlmanac
from app.services.country_almanac import get_country_almanac_store
from app.services.signal_stream import get_signal_stream

router = APIRouter(prefix="/almanac", tags=["almanac"])


@router.get("/countries/{country_id}", response_model=CountryAlmanac)
async def get_country_almanac(country_id: str) -> CountryAlmanac:
    store = get_country_almanac_store()
    country = store.get_country(country_id)
    if country is None:
        raise HTTPException(status_code=404, detail="country almanac not found")
    return country


@router.get("/countries/{country_id}/signals", response_model=AlmanacSignalResponse)
async def get_country_signals(
    country_id: str,
    limit: int = Query(default=5, ge=1, le=20),
) -> AlmanacSignalResponse:
    store = get_country_almanac_store()
    country = store.get_country(country_id)
    if country is None:
        raise HTTPException(status_code=404, detail="country almanac not found")
    stream = get_signal_stream()
    items = store.match_signals(country.id, stream.get_latest(50), limit=limit)
    return AlmanacSignalResponse(country_id=country.id, items=items)
```

- [ ] **Step 5: Register router**

Modify imports in `services/backend/app/main.py` to include `almanac`, and mount it near S1 routers:

```python
from app.routers import (
    aircraft,
    almanac,
    cables,
    ...
)
...
app.include_router(almanac.router, prefix="/api")
```

- [ ] **Step 6: Run router tests**

Run:

```bash
cd services/backend && uv run pytest tests/test_almanac_router.py tests/test_country_almanac_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit backend router**

```bash
git add services/backend/app/routers/almanac.py services/backend/app/main.py services/backend/app/services/signal_stream.py services/backend/tests/test_almanac_router.py
git commit -m "feat(backend): expose worldreport almanac endpoints"
```

## Task 3: Frontend Types, API, and Hook

**Files:**

- Create: `services/frontend/src/types/almanac.ts`
- Modify: `services/frontend/src/services/api.ts`
- Create: `services/frontend/src/hooks/useCountryAlmanac.ts`
- Test: `services/frontend/src/hooks/__tests__/useCountryAlmanac.test.tsx`

- [ ] **Step 1: Write failing hook tests**

Create `services/frontend/src/hooks/__tests__/useCountryAlmanac.test.tsx`:

```tsx
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useCountryAlmanac } from "../useCountryAlmanac";

afterEach(() => {
  vi.restoreAllMocks();
});

function mockFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/almanac/countries/GRC/signals")) {
      return new Response(JSON.stringify({ country_id: "GRC", items: [] }), { status: 200 });
    }
    if (url.includes("/api/almanac/countries/GRC")) {
      return new Response(JSON.stringify({
        id: "GRC",
        iso3: "GRC",
        m49: "300",
        name: "Greece",
        region: "Europe",
        subregion: "Southern Europe",
        capital: { name: "Athens", lat: 37.98, lon: 23.73 },
        facts: {
          profile: [{ label: "Currency", value: "Euro (EUR)" }],
          people: [],
          government: [],
          economy: [],
          security: [],
        },
        updated_at: "2026-05-19",
        source_note: "ODIN static country almanac",
      }), { status: 200 });
    }
    return new Response("not found", { status: 404 });
  });
}

describe("useCountryAlmanac", () => {
  it("fetches almanac facts and signals by iso3", async () => {
    const fetchMock = mockFetch();
    const { result } = renderHook(() => useCountryAlmanac({ iso3: "GRC", m49: "300" }));

    await waitFor(() => expect(result.current.facts.status).toBe("ready"));

    expect(result.current.facts.data?.name).toBe("Greece");
    expect(result.current.signals.status).toBe("ready");
    expect(fetchMock).toHaveBeenCalledWith("/api/almanac/countries/GRC", expect.any(Object));
    expect(fetchMock).toHaveBeenCalledWith("/api/almanac/countries/GRC/signals?limit=5", expect.any(Object));
  });

  it("falls back to m49 when iso3 is null", async () => {
    const fetchMock = mockFetch();
    renderHook(() => useCountryAlmanac({ iso3: null, m49: "732" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/almanac/countries/732", expect.any(Object));
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd services/frontend && npm test -- useCountryAlmanac.test.tsx
```

Expected: FAIL with missing `useCountryAlmanac` module.

- [ ] **Step 3: Add frontend types**

Create `services/frontend/src/types/almanac.ts`:

```ts
export interface AlmanacCapital {
  name: string;
  lat: number;
  lon: number;
}

export interface AlmanacFact {
  label: string;
  value: string;
}

export interface AlmanacFacts {
  profile: AlmanacFact[];
  people: AlmanacFact[];
  government: AlmanacFact[];
  economy: AlmanacFact[];
  security: AlmanacFact[];
}

export interface CountryAlmanac {
  id: string;
  iso3: string | null;
  m49: string;
  name: string;
  region: string;
  subregion: string;
  capital: AlmanacCapital | null;
  facts: AlmanacFacts;
  updated_at: string;
  source_note: string;
}

export interface AlmanacSignalItem {
  event_id: string;
  ts: string;
  type: string;
  title: string;
  severity: string;
  source: string;
  url: string;
}

export interface AlmanacSignalResponse {
  country_id: string;
  items: AlmanacSignalItem[];
}
```

- [ ] **Step 4: Add API helpers**

Modify `services/frontend/src/services/api.ts` imports and functions:

```ts
import type { CountryAlmanac, AlmanacSignalResponse } from "../types/almanac";

export async function getCountryAlmanac(countryId: string): Promise<CountryAlmanac> {
  const res = await fetch(`/api/almanac/countries/${encodeURIComponent(countryId)}`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`country almanac failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as CountryAlmanac;
}

export async function getCountryAlmanacSignals(
  countryId: string,
  limit = 5,
): Promise<AlmanacSignalResponse> {
  const res = await fetch(
    `/api/almanac/countries/${encodeURIComponent(countryId)}/signals?limit=${limit}`,
    { headers: { Accept: "application/json" } },
  );
  if (!res.ok) {
    throw new Error(`country almanac signals failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as AlmanacSignalResponse;
}
```

- [ ] **Step 5: Add hook**

Create `services/frontend/src/hooks/useCountryAlmanac.ts`:

```ts
import { useEffect, useMemo, useState } from "react";
import { getCountryAlmanac, getCountryAlmanacSignals } from "../services/api";
import type { AlmanacSignalResponse, CountryAlmanac } from "../types/almanac";

type LoadState<T> =
  | { status: "idle"; data: null; error: null }
  | { status: "loading"; data: null; error: null }
  | { status: "ready"; data: T; error: null }
  | { status: "error"; data: null; error: string };

const idle = <T>(): LoadState<T> => ({ status: "idle", data: null, error: null });
const loading = <T>(): LoadState<T> => ({ status: "loading", data: null, error: null });

interface Params {
  iso3: string | null;
  m49: string;
}

export function useCountryAlmanac({ iso3, m49 }: Params) {
  const countryId = useMemo(() => iso3 ?? m49, [iso3, m49]);
  const [facts, setFacts] = useState<LoadState<CountryAlmanac>>(idle);
  const [signals, setSignals] = useState<LoadState<AlmanacSignalResponse>>(idle);

  useEffect(() => {
    const controller = new AbortController();
    setFacts(loading);
    setSignals(loading);

    getCountryAlmanac(countryId)
      .then((data) => {
        if (!controller.signal.aborted) setFacts({ status: "ready", data, error: null });
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setFacts({ status: "error", data: null, error: String(err) });
      });

    getCountryAlmanacSignals(countryId, 5)
      .then((data) => {
        if (!controller.signal.aborted) setSignals({ status: "ready", data, error: null });
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setSignals({ status: "error", data: null, error: String(err) });
      });

    return () => controller.abort();
  }, [countryId]);

  return { countryId, facts, signals };
}
```

- [ ] **Step 6: Run hook tests**

Run:

```bash
cd services/frontend && npm test -- useCountryAlmanac.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit frontend hook**

```bash
git add services/frontend/src/types/almanac.ts services/frontend/src/services/api.ts services/frontend/src/hooks/useCountryAlmanac.ts services/frontend/src/hooks/__tests__/useCountryAlmanac.test.tsx
git commit -m "feat(frontend): add country almanac client hook"
```

## Task 4: Frontend Inspector Panel

**Files:**

- Create: `services/frontend/src/components/globe/spotlight/CountryAlmanacPanel.tsx`
- Modify: `services/frontend/src/components/globe/spotlight/CountryHeader.tsx`
- Modify: `services/frontend/src/components/worldview/worldviewHudLoader.css`
- Test: `services/frontend/src/components/globe/spotlight/__tests__/CountryHeader.test.tsx`

- [ ] **Step 1: Update failing component tests**

Replace `services/frontend/src/components/globe/spotlight/__tests__/CountryHeader.test.tsx` with tests that mock API fetches:

```tsx
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { CountryHeader } from "../CountryHeader";

afterEach(() => {
  vi.restoreAllMocks();
});

function mockCountryFetch(status = 200) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/signals")) {
      return new Response(JSON.stringify({
        country_id: "GRC",
        items: [{ event_id: "1", ts: "2026-05-19T10:20:00.000Z", type: "signal.rss", title: "Diplomatic statement indexed by Hugin", severity: "low", source: "rss", url: "" }],
      }), { status: 200 });
    }
    if (status !== 200) return new Response("missing", { status });
    return new Response(JSON.stringify({
      id: "GRC",
      iso3: "GRC",
      m49: "300",
      name: "Greece",
      region: "Europe",
      subregion: "Southern Europe",
      capital: { name: "Athens", lat: 37.98, lon: 23.73 },
      facts: {
        profile: [{ label: "Currency", value: "Euro (EUR)" }],
        people: [{ label: "Languages", value: "Greek" }],
        government: [],
        economy: [],
        security: [],
      },
      updated_at: "2026-05-19",
      source_note: "ODIN static country almanac",
    }), { status: 200 });
  });
}

describe("CountryHeader", () => {
  it("renders name, capital, almanac facts, and linked signals", async () => {
    mockCountryFetch();
    render(<CountryHeader name="Greece" iso3="GRC" m49="300" capital={{ name: "Athens", coords: { lon: 23.7, lat: 37.9 } }} />);

    expect(screen.getByText(/Greece/)).toBeInTheDocument();
    expect(screen.getByText(/Athens/)).toBeInTheDocument();
    expect(screen.queryByText(/S2\.5 coming soon/i)).not.toBeInTheDocument();

    expect(await screen.findByText(/WorldReport/i)).toBeInTheDocument();
    expect(screen.getByText(/Euro \(EUR\)/)).toBeInTheDocument();
    expect(screen.getByText(/Diplomatic statement indexed by Hugin/)).toBeInTheDocument();
  });

  it("falls back gracefully without iso3 and uses m49", async () => {
    mockCountryFetch();
    render(<CountryHeader name="W. Sahara" iso3={null} m49="732" capital={null} />);
    expect(screen.getByText(/W\. Sahara/)).toBeInTheDocument();
    expect(screen.getByText(/m49 · 732/)).toBeInTheDocument();
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith("/api/almanac/countries/732", expect.any(Object)));
  });

  it("keeps country title when almanac is unavailable", async () => {
    mockCountryFetch(404);
    render(<CountryHeader name="Atlantis" iso3="ATL" m49="999" capital={null} />);
    expect(screen.getByText(/Atlantis/)).toBeInTheDocument();
    expect(await screen.findByText(/unavailable for this country/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd services/frontend && npm test -- CountryHeader.test.tsx
```

Expected: FAIL because the panel component is missing and the old placeholder still renders.

- [ ] **Step 3: Add `CountryAlmanacPanel`**

Create `services/frontend/src/components/globe/spotlight/CountryAlmanacPanel.tsx`:

```tsx
import { useMemo, useState } from "react";
import { useCountryAlmanac } from "../../../hooks/useCountryAlmanac";
import type { AlmanacFact, AlmanacFacts, AlmanacSignalItem } from "../../../types/almanac";

const sections: Array<{ key: keyof AlmanacFacts; label: string }> = [
  { key: "profile", label: "Profile" },
  { key: "people", label: "People" },
  { key: "government", label: "Gov" },
  { key: "economy", label: "Economy" },
  { key: "security", label: "Security" },
];

const capabilities = ["Hugin", "Signalia", "Vectorium", "Memoria", "Fenestra"];

interface Props {
  iso3: string | null;
  m49: string;
}

export function CountryAlmanacPanel({ iso3, m49 }: Props) {
  const { facts, signals } = useCountryAlmanac({ iso3, m49 });
  const [active, setActive] = useState<keyof AlmanacFacts>("profile");

  const activeFacts = useMemo<AlmanacFact[]>(() => {
    if (facts.status !== "ready") return [];
    return facts.data.facts[active] ?? [];
  }, [active, facts]);

  return (
    <section className="country-almanac" aria-label="WorldReport Almanac">
      <div className="country-almanac__eyebrow">§ Almanac · WorldReport</div>
      {facts.status === "loading" && <div className="country-almanac__muted">§ Almanac · loading</div>}
      {facts.status === "error" && <div className="country-almanac__muted">§ Almanac · unavailable for this country</div>}
      {facts.status === "ready" && (
        <>
          <div className="country-almanac__meta">
            {[facts.data.region, facts.data.subregion].filter(Boolean).join(" · ")}
          </div>
          <div className="country-almanac__tabs" role="tablist" aria-label="Almanac sections">
            {sections.map((section) => (
              <button
                key={section.key}
                type="button"
                className={section.key === active ? "country-almanac__tab is-active" : "country-almanac__tab"}
                onClick={() => setActive(section.key)}
              >
                {section.label}
              </button>
            ))}
          </div>
          <dl className="country-almanac__facts">
            {activeFacts.length > 0 ? activeFacts.map((fact) => (
              <div className="country-almanac__fact" key={`${fact.label}:${fact.value}`}>
                <dt>{fact.label}</dt>
                <dd>{fact.value}</dd>
              </div>
            )) : (
              <div className="country-almanac__muted">No facts in this section yet</div>
            )}
          </dl>
        </>
      )}
      <SignalList status={signals.status} items={signals.status === "ready" ? signals.data.items : []} />
      <div className="country-almanac__capabilities" aria-label="ODIN capabilities">
        {capabilities.map((capability) => <span key={capability}>{capability}</span>)}
      </div>
    </section>
  );
}

function SignalList({ status, items }: { status: string; items: AlmanacSignalItem[] }) {
  return (
    <section className="country-almanac__signals" aria-label="Active ODIN signals">
      <h4>Active ODIN Signals</h4>
      {status === "loading" && <div className="country-almanac__muted">§ Signals · loading</div>}
      {status === "error" && <div className="country-almanac__muted">§ Signals · unavailable</div>}
      {status === "ready" && items.length === 0 && (
        <div className="country-almanac__muted">No linked ODIN signals in current window</div>
      )}
      {status === "ready" && items.map((item) => (
        <div className="country-almanac__signal" key={item.event_id}>
          {item.url ? (
            <a href={item.url} target="_blank" rel="noreferrer">{item.title}</a>
          ) : (
            <b>{item.title}</b>
          )}
          <span>{item.severity} · {item.source || item.type}</span>
        </div>
      ))}
    </section>
  );
}
```

- [ ] **Step 4: Replace placeholder in `CountryHeader`**

Modify `services/frontend/src/components/globe/spotlight/CountryHeader.tsx`:

```tsx
import { CountryAlmanacPanel } from "./CountryAlmanacPanel";

...
      <CountryAlmanacPanel iso3={iso3} m49={m49} />
```

Remove the old `<div className="country-placeholder">§ Almanac · S2.5 coming soon</div>`.

- [ ] **Step 5: Add styles**

Add to `services/frontend/src/components/worldview/worldviewHudLoader.css`:

```css
.country-almanac { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--granite); display: grid; gap: 10px; }
.country-almanac__eyebrow, .country-almanac__tab, .country-almanac__fact dt, .country-almanac__signals h4, .country-almanac__capabilities { font-family: "Martian Mono", ui-monospace, monospace; text-transform: uppercase; letter-spacing: .12em; }
.country-almanac__eyebrow { color: var(--ash); font-size: 9px; }
.country-almanac__meta, .country-almanac__muted { color: var(--ash); font-size: 11px; line-height: 1.45; }
.country-almanac__tabs { display: flex; flex-wrap: wrap; gap: 6px; }
.country-almanac__tab { border: 1px solid var(--granite); background: transparent; color: var(--ash); padding: 5px 7px; font-size: 9px; cursor: pointer; }
.country-almanac__tab.is-active { color: var(--parchment); border-color: var(--stone); }
.country-almanac__facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 0; }
.country-almanac__fact { border-top: 1px solid var(--granite); padding-top: 7px; }
.country-almanac__fact dt { color: var(--ash); font-size: 9px; }
.country-almanac__fact dd { margin: 3px 0 0; color: var(--parchment); font-size: 12px; line-height: 1.35; }
.country-almanac__signals { border: 1px solid var(--granite); padding: 10px; display: grid; gap: 8px; }
.country-almanac__signals h4 { margin: 0; color: var(--parchment); font-size: 10px; }
.country-almanac__signal { display: grid; gap: 3px; border-top: 1px solid var(--granite); padding-top: 7px; }
.country-almanac__signal:first-of-type { border-top: 0; padding-top: 0; }
.country-almanac__signal b, .country-almanac__signal a { color: var(--parchment); font-size: 12px; line-height: 1.35; text-decoration: none; }
.country-almanac__signal span { color: var(--ash); font-family: "Martian Mono", ui-monospace, monospace; font-size: 9px; letter-spacing: .1em; text-transform: uppercase; }
.country-almanac__capabilities { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 5px; color: var(--ash); font-size: 8px; }
.country-almanac__capabilities span { border: 1px solid var(--granite); padding: 6px 4px; text-align: center; }
@media (max-width: 720px) {
  .country-almanac__facts, .country-almanac__capabilities { grid-template-columns: 1fr; }
}
```

- [ ] **Step 6: Run component tests**

Run:

```bash
cd services/frontend && npm test -- CountryHeader.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit frontend panel**

```bash
git add services/frontend/src/components/globe/spotlight/CountryAlmanacPanel.tsx services/frontend/src/components/globe/spotlight/CountryHeader.tsx services/frontend/src/components/globe/spotlight/__tests__/CountryHeader.test.tsx services/frontend/src/components/worldview/worldviewHudLoader.css
git commit -m "feat(frontend): render worldreport almanac in inspector"
```

## Task 5: Verification and Refinement

**Files:**

- Modify any files from previous tasks only if verification reveals issues.

- [ ] **Step 1: Run backend focused tests**

Run:

```bash
cd services/backend && uv run pytest tests/test_country_almanac_service.py tests/test_almanac_router.py -q
```

Expected: PASS.

- [ ] **Step 2: Run backend quality checks**

Run:

```bash
cd services/backend && uv run ruff check app/ tests/test_country_almanac_service.py tests/test_almanac_router.py && uv run mypy app/
```

Expected: PASS. If formatting or type issues appear, fix only Almanac-related files and rerun this command.

- [ ] **Step 3: Run frontend focused tests**

Run:

```bash
cd services/frontend && npm test -- useCountryAlmanac.test.tsx CountryHeader.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Run frontend type check**

Run:

```bash
cd services/frontend && npm run type-check
```

Expected: PASS. If strict TypeScript errors appear, fix only Almanac-related files and rerun this command.

- [ ] **Step 5: Run frontend lint**

Run:

```bash
cd services/frontend && npm run lint
```

Expected: PASS. If lint errors appear, fix only Almanac-related files and rerun this command.

- [ ] **Step 6: Manual browser check**

Run:

```bash
cd services/frontend && npm run dev -- --host 0.0.0.0
```

Open `/worldview`, select Greece or another country with seed data, and verify the Inspector shows `§ Almanac · WorldReport`, facts, neutral signal empty state or linked signals, and no S2.5 placeholder.

- [ ] **Step 7: Final commit if verification required edits**

If Task 5 changed files, commit:

```bash
git add <changed-almanac-files>
git commit -m "fix: verify worldreport almanac"
```

## Self-Review

Spec coverage:

- Worldview Inspector integration: Task 4.
- Backend static country facts API: Tasks 1 and 2.
- Conservative signal matching: Tasks 1 and 2.
- Independent frontend facts/signals states: Tasks 3 and 4.
- Hlíðskjalf visual language and no fake health states: Task 4.
- TDD and verification: every implementation task starts with failing tests; Task 5 verifies.

Placeholder scan:

- No `TBD`, `TODO`, or unspecified "add tests" instructions.
- All code steps include exact file paths and concrete code blocks.

Type consistency:

- Backend response names match frontend types: `updated_at`, `source_note`, `country_id`, `items`.
- `government` is the API key while the UI label is `Gov`.
- Signal item shape matches router and frontend rendering.
