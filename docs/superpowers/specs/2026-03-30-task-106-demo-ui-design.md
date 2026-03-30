# TASK-106: Demo UI Integration — Design Spec

**Date:** 2026-03-30
**Status:** Approved
**Blocked by:** TASK-105 (done)
**Blocks:** nichts
**Scope:** C+ (demo-kritische Frontend-Integration + Demo-Playbook)

---

## 1. Executive Summary

Frontend-Integration der TASK-105 Komponenten in die bestehende WorldView UI. Drei Änderungen: (1) Tabbed Right Panel — IntelPanel + EntityExplorer teilen sich den rechten Bereich via Tabs, (2) EventLayer — Intelligence-Events als Marker auf dem CesiumJS Globe, (3) IntelPanel ReAct-Update — Mode-Badge + Tool-Chain-Anzeige. Dazu ein kurzes Demo-Playbook und ein minimales README-Update.

**Explizit out of scope:** Langfuse-Setup, polished Screenshots/GIF, große README-Überarbeitung, SSE-Änderungen, Detail-Accordion für Tool-Traces.

---

## 2. Architecture Decisions

### AD-1: Tabbed Right Panel (Option C)

**Decision:** IntelPanel und EntityExplorer teilen sich ein Panel auf der rechten Seite via Tabs. Nur ein Tab ist sichtbar. IntelPanel ist der Default-Tab.

**Why:**
- Kein neues Panel, keine Layout-Verschiebung
- Minimale Änderungen am bestehenden Layout-System (alle Panels sind absolute Overlays)
- Saubere Trennung: "Query" (Intel) vs "Explore" (Graph) als zwei Modi

### AD-2: Eigener EventLayer

**Decision:** Neuer `EventLayer.tsx` nach dem bestehenden BillboardCollection-Pattern. Eigener `useEvents()` Hook. Toggle im OperationsPanel.

**Why:**
- Folgt exakt dem bestehenden Layer-Pattern (FlightLayer, EarthquakeLayer, etc.)
- Isoliert von anderen Layern — kein Mischen von Datenquellen
- Globe-Marker sind das Kernelement der Demo

### AD-3: Minimale ReAct-Anzeige

**Decision:** Mode-Badge + kompakte Tool-Chain als eine Zeile. Kein Accordion, keine SSE-Änderungen.

**Why:**
- Demo-Fokus: zeigt dass ReAct arbeitet ohne UI-Engineering-Overhead
- Langfuse ist der richtige Ort für detailliertes Tracing

---

## 3. Event Data Contract

### Problem

Der aktuelle `GET /api/v1/graph/events` Endpoint liefert **kein `lat`/`lon`**. Events haben keine eigenen Koordinaten — die Location hängt über `(:Event)-[:OCCURRED_AT]->(:Location)` am Graph.

### Lösung

Backend-Endpoint erweitern: Cypher-Query resolved Location via `OCCURRED_AT`. Neues Response-Modell für den EventLayer.

**Erweiterte Cypher-Query:**
```cypher
MATCH (ev:Event)
OPTIONAL MATCH (ev)-[:OCCURRED_AT]->(l:Location)
RETURN ev.id AS id, ev.title AS title, ev.codebook_type AS codebook_type,
       ev.severity AS severity, ev.timestamp AS timestamp,
       l.name AS location_name, l.country AS country,
       l.lat AS lat, l.lon AS lon
ORDER BY ev.timestamp DESC
LIMIT $limit
```

**Neuer Endpoint:** `GET /api/v1/graph/events/geo`

**Query-Parameter:**
- `entity: str | None` — optional, filtert Events die ein bestimmtes Entity involvieren
- `codebook_type: str | None` — optional, filtert nach codebook_type Prefix (z.B. `military` matcht `military.*`)
- `limit: int = 100` (max 200)

Separater Endpoint statt den bestehenden `/events` zu ändern, weil:
- `/events` liefert `GraphResponse` (nodes/edges) — passt für EntityExplorer
- `/events/geo` liefert flache Liste mit Koordinaten — passt für Globe-Marker
- Kein Breaking Change

**Response-Modell:**
```python
class GeoEvent(BaseModel):
    id: str
    title: str
    codebook_type: str
    severity: str
    timestamp: str | None = None
    location_name: str | None = None
    country: str | None = None
    lat: float | None = None
    lon: float | None = None

class GeoEventsResponse(BaseModel):
    events: list[GeoEvent] = Field(default_factory=list)
    total_count: int = 0
```

**Filterung:** Events ohne `lat`/`lon` werden im Frontend ignoriert (kein Marker ohne Koordinaten). Backend liefert alle, Frontend filtert.

---

## 4. Tool-Chain-Quelle (Definitive Reihenfolge)

Die IntelPanel Tool-Chain-Anzeige nutzt folgende Fallback-Kette:

```
1. tool_trace (list[dict]) — wenn vorhanden und nicht leer
   → Extrahiere tool_name aus jedem Eintrag
   → Zeige als: "qdrant_search → graph_query → classify → synthesis"

2. agent_chain (list[str]) — wenn tool_trace leer
   → Zeige als: "osint_agent → analyst_agent → synthesis_agent"

3. Nichts rendern — wenn beide leer
```

**Mode-Mapping (fix):**

| `mode` Wert | Badge-Text | Badge-Farbe |
|-------------|-----------|-------------|
| `"react"` | ReAct | blue-500 |
| `"legacy"` | Legacy | amber-500 |
| `"legacy_fallback"` | Fallback | red-500 |
| `"error"` | Error | red-600 |
| undefined/missing | — | nicht rendern |

---

## 5. Component Changes

### 5.1 Tabbed Right Panel

**Neues Wrapper-Component:** `RightPanel.tsx`

Wrappt IntelPanel + EntityExplorer mit Tab-UI. Wird in `App.tsx` anstelle des bisherigen `<IntelPanel>` gerendert.

**WICHTIG — Positioning-Migration:** IntelPanel hat aktuell seine eigene absolute Positionierung (`absolute right-3 top-16 w-80 ... z-40`). Diese Positionierung muss nach **RightPanel** wandern. IntelPanel selbst wird zu einem relativ-positionierten Kind-Element ohne eigene `absolute`/`right`/`top` Klassen.

Konkret:
1. `RightPanel.tsx` übernimmt: `absolute right-3 top-16 w-80 z-40 max-h-[calc(100vh-120px)]`
2. `IntelPanel.tsx` wird modifiziert: Die äußere `<div>` verliert `absolute right-3 top-16 w-80 z-40`, behält nur `bg-black/85 border border-green-500/20 rounded font-mono text-xs backdrop-blur-sm flex flex-col`
3. Der `max-h` Constraint wird vom RightPanel verwaltet, nicht von IntelPanel

```
<RightPanel>   ← absolute right-3 top-16 w-80 z-40
  <TabBar />   ← INTEL | GRAPH Tabs
  Tab "INTEL" → <IntelPanel ...props />   ← keine eigene absolute Position mehr
  Tab "GRAPH" → <EntityExplorer ...props />
</RightPanel>
```

**Tab-Styling:** Folgt dem bestehenden Design-System:
- Background: `bg-[#111]` / `bg-[var(--color-surface)]`
- Active Tab: Bottom-Border `border-b-2 border-green-400` (Intel) / `border-blue-500` (Graph)
- Inactive Tab: `text-green-400/40`
- Font: JetBrains Mono, 10px, uppercase

**Props von App.tsx:**
- IntelPanel `onQuery` Signatur ändert sich: `onQuery(query: string)` → `onQuery(query: string, useLegacy: boolean)`. Alternativ: `onQuery(query: IntelQuery)` mit dem bestehenden `IntelQuery`-Interface (das jetzt `use_legacy` enthält). Empfehlung: `onQuery(query: string, useLegacy: boolean)` — minimale Änderung, kein neuer Import nötig in IntelPanel.
- Alle anderen IntelPanel-Props bleiben unverändert
- EntityExplorer bekommt `apiBaseUrl="/api/v1/graph"`

### 5.2 EventLayer

**Neuer Layer:** `src/components/layers/EventLayer.tsx`

**Pattern:** Identisch zu EarthquakeLayer — BillboardCollection + LabelCollection.

**Icons nach codebook_type Kategorie:**

| Kategorie-Prefix | Icon-Shape | Farbe |
|---|---|---|
| `military.*` | ◆ Diamond | `#ef4444` (red) |
| `space.*` | ★ Star | `#06b6d4` (cyan) |
| `cyber.*` | ⬡ Hexagon | `#a855f7` (purple) |
| `political.*` | ■ Square | `#f97316` (orange) |
| `economic.*` | ▲ Triangle | `#eab308` (yellow) |
| `environmental.*` | ● Circle | `#22c55e` (green) |
| `other.*` / default | ○ Ring | `#6b7280` (gray) |

Icons werden als Canvas-gezeichnete Shapes gerendert (wie FlightLayer), nicht als externe Bilder.

**Props:**
```typescript
interface EventLayerProps {
  viewer: Cesium.Viewer | null;
  visible: boolean;
}
```

**Billboard Property Schema für Click-Handling:**

BillboardCollection-Items sind keine Cesium Entities — sie werden über `picked.primitive` identifiziert, nicht `picked.id`. EventLayer speichert Event-Metadaten als Custom Properties auf jedem Billboard:

```typescript
billboard.id = event.id;                    // string — unique event ID
billboard._eventData = {                    // custom property
  title: event.title,
  codebook_type: event.codebook_type,
  severity: event.severity,
  location_name: event.location_name,
  lat: event.lat,
  lon: event.lon,
};
```

**Klick-Verhalten:** EntityClickHandler erweitern mit expliziter Guard-Reihenfolge:

```typescript
// Guard 1: Event-Billboard (neues Pattern)
if (picked?.primitive?._eventData) {
  const data = picked.primitive._eventData;
  setSelected({ ... });  // render event popup
  return;
}

// Guard 2: Bestehende Cesium Entity Logik (unchanged)
if (Cesium.defined(picked) && picked.id) {
  // ... existing entity handling ...
}
```

Event-Billboards werden **zuerst** geprüft. Nur wenn kein `_eventData` vorhanden, greift die bestehende Entity-Logik. So kein Regression-Risiko im aktuellen Handler.

**Popup zeigt:** Title, codebook_type, Severity, Location-Name. Kein Fly-to (Events sind schon sichtbar).

### 5.3 useEvents Hook

**Neuer Hook:** `src/hooks/useEvents.ts`

```typescript
function useEvents(enabled: boolean): {
  events: IntelEvent[];
  loading: boolean;
  lastUpdate: Date | null;
}
```

**Polling:** Alle 60 Sekunden (Events ändern sich langsam).
**Endpoint:** `GET /api/v1/graph/events/geo?limit=100`
**Filterung:** Nur Events mit `lat !== null && lon !== null` werden in `events` returned.

### 5.4 IntelPanel ReAct-Update

**Änderungen an `IntelPanel.tsx`:**

1. **Mode-Badge** — neben dem Threat-Assessment Badge:
   ```tsx
   {result.mode && (
     <span className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase ${MODE_COLORS[result.mode]}`}>
       {MODE_LABELS[result.mode]}
     </span>
   )}
   ```

2. **Tool-Chain-Zeile** — unter dem Ergebnis-Header:
   ```tsx
   {toolChain.length > 0 && (
     <div className="text-[10px] text-green-400/60 font-mono mt-1">
       {toolChain.join(" → ")}
     </div>
   )}
   ```

3. **Logik:**
   ```typescript
   const toolChain = result.tool_trace?.length
     ? result.tool_trace.map(t => t.tool_name)
     : result.agent_chain?.length
       ? result.agent_chain
       : [];
   ```

### 5.5 TypeScript Updates

**`types/index.ts` — neue/erweiterte Interfaces:**

```typescript
// Erweiterung
export interface IntelAnalysis {
  // ... bestehende Felder ...
  tool_trace: Array<{ tool_name: string; duration_ms?: number; success?: boolean }>;
  mode: "react" | "legacy" | "legacy_fallback" | "error";
}

// Neue Interfaces
export interface IntelEvent {
  id: string;
  title: string;
  codebook_type: string;
  severity: string;
  timestamp: string | null;
  location_name: string | null;
  country: string | null;
  lat: number;
  lon: number;
}

export interface LayerVisibility {
  flights: boolean;
  satellites: boolean;
  earthquakes: boolean;
  vessels: boolean;
  cctv: boolean;
  events: boolean;    // NEW
}
```

---

## 6. File Changes Summary

### New Files

```
services/frontend/src/
├── components/
│   ├── ui/RightPanel.tsx            # Tab wrapper (Intel + Graph)
│   └── layers/EventLayer.tsx        # Globe event markers
├── hooks/useEvents.ts               # Event polling hook

services/backend/
├── app/models/events.py             # GeoEvent, GeoEventsResponse
```

### Modified Files

```
services/frontend/src/
├── App.tsx                          # Replace <IntelPanel> with <RightPanel>, add EventLayer, add events to LayerVisibility
├── types/index.ts                   # Add IntelEvent, extend IntelAnalysis, extend LayerVisibility
├── components/ui/IntelPanel.tsx     # Remove absolute positioning, add mode badge + tool chain + use_legacy toggle
├── components/ui/OperationsPanel.tsx # Add EVENTS toggle
├── components/ui/StatusBar.tsx      # Add EVENTS count
├── services/api.ts                  # Add getGeoEvents(), extend queryIntel() with use_legacy param
├── hooks/useIntel.ts                # Extend runQuery() to accept use_legacy

services/backend/
├── app/routers/graph.py             # Add GET /graph/events/geo endpoint
```

---

## 7. Demo-Playbook (Deliverable 4)

**File:** `docs/demo-playbook.md`

Inhalt:
1. Prerequisites (docker compose up, welche Services laufen müssen)
2. Seed-Daten: Wie man den Feed-Crawl triggert (oder Testdaten lädt)
3. Demo-Flow:
   - Query: "What Chinese military satellites were launched recently?"
   - Was passiert: ReAct Agent → qdrant_search → graph_query → synthesis
   - Was man sieht: Mode-Badge "ReAct", Tool-Chain, Globe-Marker bei Jiuquan
   - Tab-Switch zu Graph: Entity-Netzwerk um "Yaogan-44"
4. Fallback-Demo: Checkbox "Legacy Mode" im IntelPanel Query-Form → `use_legacy=true` wird mitgeschickt → Badge zeigt "Legacy"

**Hinweis:** Die `use_legacy` Checkbox ist ein kleiner UI-Toggle im Query-Form (unter dem Textarea). Wird in `IntelPanel.tsx` als State verwaltet, an `onQuery` weitergegeben, und durch `api.ts` → Backend → Intelligence-Service propagiert. Keine neuen SSE-Events nötig — nur der JSON-Payload bekommt das Feld.

**Kein README-Rewrite** — nur ein kurzer Abschnitt "Demo" am Ende des bestehenden README mit Link zum Playbook.

---

## 8. Testing Strategy

### Frontend
- Type-check: `npm run type-check` muss grün sein
- Build: `npm run build` muss durchlaufen
- Lint: `npm run lint` keine neuen Errors

### Backend
- Unit-Test für `/graph/events/geo` Endpoint (~3 Tests: mit Location, ohne Location, mit Entity-Filter)
- Current backend test suite must remain green

### Regression
- Current test suites across all services must remain green
- Bestehende UI-Funktionalität unverändert (Layer-Toggles, Shader, Intel-Query)

---

## 9. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| react-force-graph-2d TypeScript-Errors in Tab-Context | Build-Fehler | Type declarations existieren bereits von TASK-105 |
| EventLayer Performance bei vielen Events | Globe lag | LIMIT 100 + nur Events mit Koordinaten |
| IntelPanel Props-Change bricht bestehende Nutzung | Runtime-Error | Neue Felder sind optional (tool_trace, mode) |
| Events ohne Location (kein OCCURRED_AT) | Leere Map | Frontend filtert Events ohne lat/lon — kein Crash |
| CesiumJS BillboardCollection Lifecycle | Memory Leak | Folgt exakt bestehendes Pattern (cleanup in useEffect return) |
