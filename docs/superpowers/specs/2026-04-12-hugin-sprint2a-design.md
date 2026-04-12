# Hugin Sprint 2a: Conflict + Disaster Collectors

**Date:** 2026-04-12
**Status:** Draft
**Context:** Last feature sprint before major app restructure (Landing Page + Worldview + Briefing Room)

## Goal

Five new data collectors for conflict monitoring, natural disasters, maritime chokepoints, and tropical weather. Two of them (EONET, GDACS) get Globe-Layer visualization. All follow the existing BaseCollector pattern with Qdrant/Neo4j ingestion.

## Architectural Decisions

### BaseCollector Pattern (unchanged)

All collectors inherit from `feeds/base.py:BaseCollector` and implement `collect()`:
Fetch → Parse → Dedup (SHA-256 content hash) → Pipeline (vLLM extract → Neo4j) → Embed (TEI) → Qdrant upsert.

### Globe-Layer: Only EONET + GDACS

EONET and GDACS produce discrete geo-located events (volcanoes, storms, disasters with coordinates) — natural globe points. HAPI delivers monthly country aggregates, PortWatch delivers chokepoint flow metrics, NOAA NHC delivers hurricane track data — these need different visualizations that will be designed during the app restructure.

### Frontend: INGESTION_LAYERS

EONET and GDACS Globe-Layers go into `INGESTION_LAYERS` in OperationsPanel (same as FIRMS/MilAircraft), not CORE_LAYERS — they're ingestion-sourced dynamic data.

### Scheduling

| Collector | Trigger | Rationale |
|-----------|---------|-----------|
| EONET | IntervalTrigger, 2h | Events unfold over hours/days |
| GDACS | IntervalTrigger, 2h | Disaster alerts update slowly |
| HAPI | CronTrigger, daily 04:00 UTC | Monthly aggregates, daily check |
| NOAA NHC | IntervalTrigger, 3h | Hurricane advisories every 6h, 3h gives good coverage |
| PortWatch | IntervalTrigger, 6h | Daily flow data |

All with `coalesce=True`, `max_instances=1`, `misfire_grace_time=300`.

---

## Collector 1: EONET (NASA Earth Observatory Natural Events)

### API

- **Endpoint:** `https://eonet.gsfc.nasa.gov/api/v3/events`
- **Auth:** None
- **Params:** `status=open&days=30` (open events, last 30 days)
- **Response:** JSON with `events[]`, each has `id`, `title`, `categories[]`, `geometry[]` (with coordinates + date)
- **Rate Limit:** None documented, use 2s delay between paginated requests

### Categories

EONET categorizes events: `wildfires`, `volcanoes`, `severeStorms`, `seaLakeIce`, `earthquakes`, `floods`, `landslides`, `dustHaze`, `drought`, `snow`, `tempExtremes`, `waterColor`, `manmade`.

### Content Hash

`sha256(event_id)` — EONET events have stable IDs.

### Qdrant Payload

```python
{
    "source": "eonet",
    "eonet_id": str,
    "title": str,
    "category": str,          # primary category
    "status": str,             # "open" | "closed"
    "latitude": float,
    "longitude": float,
    "event_date": str,         # ISO date of latest geometry
    "ingested_epoch": float,
    "description": str,        # "{title} - {category} event at {coordinates}"
}
```

### Globe-Layer

- **Backend Router:** `GET /api/v1/eonet/events?since_hours=168` — query Qdrant by source+ingested_epoch
- **Frontend Hook:** `useEONETEvents(enabled)` — polls every 120s when enabled
- **Icons by category:**
  - Volcanoes: red triangle (#ef4444)
  - Wildfires: orange flame (#f97316)
  - Severe Storms: purple cyclone (#a855f7)
  - Floods/Sea/Ice: blue drop (#3b82f6)
  - Other: gray circle (#9ca3af)
- **Labels:** Event title at altitude < 5M meters
- **SelectionPanel:** Title, Category, Status, Date, Coordinates

### Schedule

IntervalTrigger, every 2 hours. Run on startup.

---

## Collector 2: GDACS (Global Disaster Alert & Coordination System)

### API

- **Endpoint:** `https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP`
- **Auth:** None
- **Response:** GeoJSON FeatureCollection with disaster events
- **Fields per feature:** `properties.eventtype` (EQ/TC/FL/VO/DR/WF), `properties.alertlevel` (Red/Orange/Green), `properties.eventname`, `properties.severity.value`, `properties.country`, `properties.fromdate`, `properties.todate`, `geometry.coordinates`

### Content Hash

`sha256(eventtype + eventid)` — GDACS events have type+id pairs.

### Qdrant Payload

```python
{
    "source": "gdacs",
    "gdacs_id": str,
    "event_type": str,         # EQ, TC, FL, VO, DR, WF
    "event_name": str,
    "alert_level": str,        # Red, Orange, Green
    "severity": float,
    "country": str,
    "latitude": float,
    "longitude": float,
    "from_date": str,
    "to_date": str,
    "ingested_epoch": float,
    "description": str,
}
```

### Globe-Layer

- **Backend Router:** `GET /api/v1/gdacs/events?since_hours=168`
- **Frontend Hook:** `useGDACSEvents(enabled)` — polls every 120s
- **Icons by alert level:**
  - Red: large red circle (#ef4444), pulsing ring (like FIRMS explosion)
  - Orange: medium orange circle (#f97316)
  - Green: small green circle (#22c55e)
- **Labels:** Event name at altitude < 5M meters
- **SelectionPanel:** Name, Type (EQ/TC/FL/VO/DR/WF expanded), Alert Level, Severity, Country, Date Range

### Schedule

IntervalTrigger, every 2 hours. Run on startup.

---

## Collector 3: HAPI (Humanitarian Data Exchange)

### API

- **Endpoint:** `https://hapi.humdata.org/api/v2/coordination-context/conflict-events`
- **Auth:** `app_identifier` header = Base64 encoded email (attribution only, no key)
- **Params:** `output_format=json&limit=1000&location_code={ISO3}`
- **Response:** Monthly aggregates per country: `events`, `fatalities`, `event_type` (political_violence, civilian_targeting, demonstration)
- **Countries (20 focus):** AF, SY, UA, SD, SS, SO, CD, MM, YE, ET, IQ, PS, LY, ML, BF, NE, NG, CM, MZ, HT

### Content Hash

`sha256(location_code + reference_period + event_type)` — one record per country-month-type.

### Qdrant Payload

```python
{
    "source": "hapi",
    "location_code": str,      # ISO3
    "reference_period": str,   # YYYY-MM
    "event_type": str,
    "events_count": int,
    "fatalities": int,
    "ingested_epoch": float,
    "description": str,        # "{event_type}: {events_count} events, {fatalities} fatalities in {country} ({period})"
}
```

### No Globe-Layer

Monthly country aggregates — no individual point coordinates. Visualization deferred to Briefing Room.

### Schedule

CronTrigger, daily at 04:00 UTC.

---

## Collector 4: NOAA NHC (Tropical Weather)

### API

- **Endpoint:** `https://www.nhc.noaa.gov/CurrentSummaries.json`
- **Fallback:** `https://www.nhc.noaa.gov/gis/forecast/archive/` for GIS shapefiles
- **Auth:** None
- **Response:** JSON with active tropical cyclones, positions, intensity, forecast tracks

### Content Hash

`sha256(storm_id + advisory_number)` — unique per advisory update.

### Qdrant Payload

```python
{
    "source": "noaa_nhc",
    "storm_id": str,
    "storm_name": str,
    "classification": str,     # "Tropical Storm", "Hurricane Cat 1-5", "Tropical Depression"
    "wind_speed_kt": int,
    "pressure_mb": int,
    "latitude": float,
    "longitude": float,
    "movement": str,           # "NW at 12 kt"
    "advisory_number": str,
    "ingested_epoch": float,
    "description": str,
}
```

### No Globe-Layer

Hurricane tracks need polyline visualization (forecast cone) — deferred to app restructure.

### Schedule

IntervalTrigger, every 3 hours. Run on startup.

---

## Collector 5: IMF PortWatch (Chokepoint Flows)

### API

- **Base:** `https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/`
- **Endpoints:**
  - `Daily_Chokepoints_Data/FeatureServer/0/query` — daily flows
  - `portwatch_disruptions_database/FeatureServer/0/query` — disruption events
- **Auth:** None
- **Query:** `where=1=1&outFields=*&f=json&resultRecordCount=1000`
- **Chokepoints:** Hormuz, Bab-el-Mandeb, Suez, Malakka, Panama, Good Hope, Gibraltar, Turkish Straits

### Content Hash

`sha256(chokepoint_name + date + flow_type)` for daily data.
`sha256(disruption_id)` for disruption events.

### Qdrant Payload

```python
# Daily flow
{
    "source": "portwatch",
    "record_type": "daily_flow",
    "chokepoint": str,
    "date": str,
    "trade_value_usd": float,
    "vessel_count": int,
    "latitude": float,          # chokepoint center
    "longitude": float,
    "ingested_epoch": float,
    "description": str,
}

# Disruption event
{
    "source": "portwatch",
    "record_type": "disruption",
    "disruption_id": str,
    "chokepoint": str,
    "description": str,
    "start_date": str,
    "end_date": str | None,
    "latitude": float,
    "longitude": float,
    "ingested_epoch": float,
}
```

### No Globe-Layer

Chokepoint flow data needs specialized visualization (flow arrows, disruption timeline) — deferred.

### Schedule

IntervalTrigger, every 6 hours. Run on startup.

---

## Files Changed

### New files (services/data-ingestion):
- `feeds/eonet_collector.py`
- `feeds/gdacs_collector.py`
- `feeds/hapi_collector.py`
- `feeds/noaa_nhc_collector.py`
- `feeds/portwatch_collector.py`

### Modified files (services/data-ingestion):
- `scheduler.py` — add 5 new collector jobs

### New files (services/backend):
- `app/routers/eonet.py`
- `app/routers/gdacs.py`

### Modified files (services/backend):
- `app/main.py` — register eonet + gdacs routers

### New files (services/frontend):
- `src/hooks/useEONETEvents.ts`
- `src/hooks/useGDACSEvents.ts`
- `src/components/layers/EONETLayer.tsx`
- `src/components/layers/GDACSLayer.tsx`

### Modified files (services/frontend):
- `src/types/index.ts` — EONETEvent + GDACSEvent types, LayerVisibility extension
- `src/components/ui/OperationsPanel.tsx` — add to INGESTION_LAYERS
- `src/components/ui/SelectionPanel.tsx` — add EONET + GDACS content
- `src/App.tsx` — wire hooks, render layers

## Testing

### Collector tests (services/data-ingestion):
- Each collector: parse/transform logic, dedup hash, API response handling
- Mock httpx responses, verify Qdrant payload structure

### Backend tests (services/backend):
- Router tests for eonet + gdacs endpoints
- Mock Qdrant scroll, verify response schema

### Frontend tests (services/frontend):
- Hook tests (enabled-gating, fetch mock)
- Layer tests (billboard count, visibility toggle, icon creation)
- Integration tests (OperationsPanel toggles, SelectionPanel content)
- Type-check + lint clean

## Environment Variables

```env
# HAPI (required for HAPI collector)
HAPI_APP_IDENTIFIER=base64_encoded_email

# All others: no auth needed
```
