# Hugin P0 Collectors — Design Spec

> 6 neue OSINT-Collectors für die Odin Data-Ingestion Pipeline. Destilliert aus dem Hugin Source Catalog (WorldMonitor-Referenz). Fokus: Conflict Intelligence, Geospatial Activity, Sanctions.

**Datum:** 2026-04-09
**Status:** Draft
**Referenz:** `~/DeadpoolsSec/ODIN/HUGIN_SOURCE_CATALOG.md`

---

## Übersicht

| # | Collector | Quelle | Auth | Scheduler | Pipeline |
|---|-----------|--------|------|-----------|----------|
| 1 | `acled_collector.py` | ACLED API | OAuth2 Password | 6h | `process_item()` → Neo4j + Qdrant |
| 2 | `ucdp_collector.py` | UCDP GED API | Free (optional token) | 12h | `process_item()` → Neo4j + Qdrant |
| 3 | `firms_collector.py` | NASA FIRMS | API Key | 2h | `process_item()` → Neo4j + Qdrant |
| 4 | `usgs_collector.py` | USGS Earthquake | Free | 6h | `process_item()` → Neo4j + Qdrant |
| 5 | `military_aircraft_collector.py` | adsb.fi + OpenSky | Free / OAuth2 | 15min | Direct Neo4j + Qdrant (kein LLM) |
| 6 | `ofac_collector.py` | US Treasury OFAC | Free | Daily 03:30 | Direct Neo4j + Qdrant (kein LLM) |

---

## 1. Architektur: BaseCollector

### Problem

Die bestehenden Collectors (GDELT, RSS, Telegram) duplizieren Qdrant-Setup, Embedding, Dedup und Batch-Upsert. Mit 6 neuen Collectors wird das unhaltbar.

### Lösung

`services/data-ingestion/feeds/base.py` — abstrakte Basisklasse für alle neuen Collectors.

```python
class BaseCollector(ABC):
    """Gemeinsame Logik für alle Hugin Collectors."""

    def __init__(self, settings: Settings, redis_client: Redis | None = None):
        self.settings = settings
        self.redis = redis_client
        self.qdrant = QdrantClient(url=settings.qdrant_url)
        self.http = httpx.AsyncClient(timeout=settings.http_timeout)
        self._collection_ready = False

    async def _ensure_collection(self) -> None:
        """Qdrant Collection erstellen falls nicht vorhanden."""
        if self._collection_ready:
            return
        collections = await asyncio.to_thread(
            lambda: self.qdrant.get_collections().collections
        )
        if not any(c.name == self.settings.qdrant_collection for c in collections):
            await asyncio.to_thread(
                self.qdrant.create_collection,
                collection_name=self.settings.qdrant_collection,
                vectors_config=VectorParams(
                    size=self.settings.embedding_dimensions,
                    distance=Distance.COSINE,
                ),
            )
        self._collection_ready = True

    async def _embed(self, text: str) -> list[float]:
        """Text-Embedding via TEI."""
        resp = await self.http.post(
            f"{self.settings.tei_embed_url}/embed",
            json={"inputs": text, "truncate": True},
        )
        resp.raise_for_status()
        return resp.json()[0]

    def _content_hash(self, *parts: str) -> str:
        """SHA256 Content-Hash aus beliebig vielen Teilen."""
        raw = "|".join(p.lower().strip() for p in parts)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _point_id(self, content_hash: str) -> int:
        """64-bit positive Integer aus Content-Hash."""
        return int(content_hash[:16], 16)

    async def _dedup_check(self, point_id: int) -> bool:
        """True wenn Point bereits in Qdrant existiert."""
        existing = await asyncio.to_thread(
            self.qdrant.retrieve,
            collection_name=self.settings.qdrant_collection,
            ids=[point_id],
        )
        return len(existing) > 0

    async def _batch_upsert(self, points: list[PointStruct]) -> None:
        """Batch-Upsert in Qdrant."""
        if not points:
            return
        await asyncio.to_thread(
            self.qdrant.upsert,
            collection_name=self.settings.qdrant_collection,
            points=points,
        )

    async def _build_point(
        self, text: str, payload: dict, content_hash: str
    ) -> PointStruct:
        """Embedding generieren + PointStruct bauen."""
        vector = await self._embed(text)
        point_id = self._point_id(content_hash)
        payload["content_hash"] = content_hash
        payload["ingested_at"] = datetime.now(timezone.utc).isoformat()
        return PointStruct(id=point_id, vector=vector, payload=payload)

    @abstractmethod
    async def collect(self) -> None:
        """Hauptmethode — wird vom Scheduler aufgerufen."""
        ...

    async def close(self) -> None:
        """HTTP-Client schließen."""
        await self.http.aclose()
```

### Migration bestehender Collectors

Bestehende Collectors (GDELT, RSS, Telegram) werden **nicht** migriert. Kein Refactoring ohne Feature-Wert. Die BaseCollector-Klasse wird nur von neuen Collectors genutzt.

---

## 2. Collector: ACLED (Armed Conflict Location & Event Data)

### Datenwert

Manuell kuratierte Konfliktdaten — die Grundwahrheit für bewaffnete Konflikte weltweit. Komplementär zu GDELT (automatisch) und UCDP (akademisch).

### Auth

OAuth2 Password Grant:
```
POST https://acleddata.com/oauth/token
Body: grant_type=password, client_id=acled, username={email}, password={pw}
Response: { access_token } → Authorization: Bearer {token}
```
Token wird gecacht und bei 401 automatisch refreshed.

### Query

```
GET https://acleddata.com/api/acled/read
  ?event_type=Battles|Explosions/Remote violence|Violence against civilians
  &event_date={30_days_ago}|{today}
  &event_date_where=BETWEEN
  &limit=500
  &_format=json
```

Pagination: `limit=500`, `page=1,2,...` bis leere Response.

### Rate Limiting

Nicht dokumentiert. Defensiv: 300ms Sleep zwischen Requests.

### Dedup

Content-Hash: `acled_event_id_cnty` (ACLED's eigene eindeutige ID).

### Pipeline

Standard `process_item()` — vLLM extrahiert Entities/Events aus ACLED's Textfeldern (`notes`, `source`).

### Qdrant-Payload

```python
{
    "source": "acled",
    "title": str,           # event_type + location
    "url": str,             # acleddata.com deep link
    "acled_event_id": str,  # event_id_cnty
    "event_type": str,      # Battles, Explosions/Remote violence, etc.
    "sub_event_type": str,  # Armed clash, Shelling/artillery/missile, etc.
    "fatalities": int,
    "actor1": str,
    "actor2": str,
    "admin1": str,          # Province/State
    "country": str,
    "latitude": float,
    "longitude": float,
    "event_date": str,      # ISO date
}
```

### Scheduler

`IntervalTrigger(hours=6)` — ACLED hat 1-2 Tage Lag, häufigeres Polling verschwendet Credits.

### Config

```python
acled_email: str = ""       # .env: ACLED_EMAIL
acled_password: str = ""    # .env: ACLED_PASSWORD
```

### Caveats

- Non-commercial License — nur für interne Analyse
- OAuth Token kann expiren → Auto-Refresh bei 401

---

## 3. Collector: UCDP GED (Uppsala Conflict Data Program)

### Datenwert

Akademischer Gegencheck zu ACLED. Tiefere Zeitreihen (bis 1989). Unabhängige Kuratierung durch Uppsala University.

### Auth

Optional `x-ucdp-access-token` Header. Funktioniert auch ohne.

### Version Discovery

UCDP API-Version ist nicht stabil. Sequentiell probieren:

```python
current_year = datetime.now().year
versions = [f"{current_year - 2000}.1", f"{current_year - 2001}.1", "25.1", "24.1"]
for version in versions:
    resp = await self.http.get(f"https://ucdpapi.pcr.uu.se/api/gedevents/{version}?pagesize=1&page=0")
    if resp.status_code == 200 and resp.json().get("Result"):
        break
```

### Query

```
GET https://ucdpapi.pcr.uu.se/api/gedevents/{version}
  ?pagesize=1000
  &page={0..5}
  &StartDate={365_days_ago}
  &EndDate={today}
```

Max 6 Pages (6000 Events). `StartDate`/`EndDate` erzwingen das 365-Tage-Window explizit. Falls >6000 Events in 365 Tagen anfallen, wird ein Warning geloggt — in der Praxis reicht das Limit.

### Timeout

90s — UCDP ist notorisch langsam.

### Dedup

Content-Hash: `ucdp_id` (UCDP's eigene Event-ID).

### Pipeline

Standard `process_item()`.

### Qdrant-Payload

```python
{
    "source": "ucdp",
    "title": str,
    "url": str,
    "ucdp_id": str,
    "violence_type": int,        # 1=STATE_BASED, 2=NON_STATE, 3=ONE_SIDED
    "violence_type_label": str,
    "best_estimate": int,        # Fatalities best estimate
    "low_estimate": int,
    "high_estimate": int,
    "country": str,
    "region": str,
    "latitude": float,
    "longitude": float,
    "date_start": str,
    "date_end": str,
    "side_a": str,
    "side_b": str,
}
```

### Scheduler

`IntervalTrigger(hours=12)` — akademische Daten, langsames Update.

### Config

```python
ucdp_access_token: str = ""  # .env: UCDP_ACCESS_TOKEN (optional)
```

---

## 4. Collector: NASA FIRMS (Fire Information for Resource Management)

### Datenwert

Gold-Quelle für thermische Anomalien. Cross-Korrelation mit ACLED ermöglicht verifizierte Kampfhandlungs-Erkennung. Die Explosion-Heuristik (`frp > 80 AND brightness > 380`) ist ein Alleinstellungsmerkmal.

### Auth

NASA Earthdata API Key — kostenlose Registrierung.

### Endpoints

3 Satelliten-Sources parallel (alle 3 fetchen und dedupen):

```
https://firms.modaps.eosdis.nasa.gov/api/area/csv/{API_KEY}/VIIRS_SNPP_NRT/{BBOX}/1
https://firms.modaps.eosdis.nasa.gov/api/area/csv/{API_KEY}/VIIRS_NOAA20_NRT/{BBOX}/1
https://firms.modaps.eosdis.nasa.gov/api/area/csv/{API_KEY}/VIIRS_NOAA21_NRT/{BBOX}/1
```

**BBOX-Format**: `west,south,east,north` (nicht lat/lon!).

### Monitored Regions

```python
FIRMS_BBOXES = {
    "ukraine":      "22,44,40,53",
    "russia":       "20,50,180,82",
    "iran":         "44,25,63,40",
    "israel_gaza":  "34,29,36,34",
    "syria":        "35,32,42,37",
    "taiwan":       "119,21,123,26",
    "north_korea":  "124,37,131,43",
    "saudi_arabia": "34,16,56,32",
    "turkey":       "26,36,45,42",
}
```

### Explosion-Heuristik

```python
possible_explosion = frp > 80 and brightness > 380
```

Dieses Flag wird im Qdrant-Payload und Neo4j-Event gespeichert. Kein separater Alarm — die Cross-Korrelation mit ACLED ist ein eigenes Feature.

### Rate Limiting

10 req/min → 6s Sleep zwischen Calls. Bei 9 Regions × 3 Satelliten = 27 Calls → ~3 Minuten pro Collection-Run.

### Dedup

Content-Hash: `{latitude_rounded_4dp}|{longitude_rounded_4dp}|{acq_date}|{acq_time}` — ohne `satellite`, damit identische Hotspots von verschiedenen Satelliten dedupliziert werden. Bei gleichem Ort/Zeitpunkt gewinnt der erste Satellite-Hit.

### Pipeline

Standard `process_item()` — vLLM klassifiziert den Kontext (Waldbrand vs. industriell vs. mögliche Explosion).

### Qdrant-Payload

```python
{
    "source": "firms",
    "title": str,               # "Thermal anomaly in {bbox_name}"
    "url": str,                 # NASA FIRMS deep link
    "satellite": str,           # VIIRS_SNPP_NRT, etc.
    "brightness": float,        # bright_ti4
    "frp": float,               # Fire Radiative Power (MW)
    "confidence": str,          # "high", "nominal", "low"
    "daynight": str,            # "D" or "N"
    "bbox_name": str,           # "ukraine", "iran", etc.
    "latitude": float,
    "longitude": float,
    "acq_date": str,
    "acq_time": str,
    "possible_explosion": bool,
}
```

### Scheduler

`IntervalTrigger(hours=2)` — Satellit-Latenz ~3h.

### Config

```python
nasa_earthdata_key: str = ""  # .env: NASA_EARTHDATA_KEY
```

---

## 5. Collector: USGS Earthquake (Nuclear-Enriched)

### Datenwert

Erdbeben-Daten mit Nuclear Test Site Proximity-Enrichment. Seismische Events nahe bekannten Testgeländen bekommen einen Concern-Score für Nuclear Monitoring.

### Endpoint

```
GET https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson
```

Keine Auth. GeoJSON-Format.

### Nuclear Test Sites

```python
NUCLEAR_TEST_SITES = {
    "Punggye-ri (DPRK)":     (41.28, 129.08),
    "Lop Nur (China)":       (41.39, 89.03),
    "Novaya Zemlya (Russia)": (73.37, 54.78),
    "Nevada NTS (USA)":      (37.07, -116.05),
    "Semipalatinsk (KZ)":    (50.07, 78.43),
}
```

### Concern-Score Berechnung

Für jedes Erdbeben innerhalb von 100km eines Test-Sites:

```python
def concern_score(magnitude: float, distance_km: float, depth_km: float) -> float:
    mag_factor = (magnitude / 9.0) * 0.6
    dist_factor = ((100 - distance_km) / 100) * 0.25
    # Nukleartests sind typischerweise flach (<10km)
    depth_factor = (1.0 if depth_km < 5 else 0.5 if depth_km < 15 else 0.1) * 0.15
    return round((mag_factor + dist_factor + depth_factor) * 100, 1)
```

Concern-Levels:
- `≥75`: critical
- `≥50`: elevated
- `≥25`: moderate
- `<25`: none (kein Enrichment)

### Abgrenzung zum Backend-Router

Der bestehende `routers/earthquakes.py` bleibt für Live-Globe-Visualisierung (fetch-and-forward, kein State). Dieser Collector macht Intelligence-Enrichment: Nuclear-Score-Berechnung, Neo4j-Persistenz, Qdrant-Embedding.

### Dedup

Content-Hash: USGS `id` (z.B. `us7000n1a2`).

### Pipeline

Standard `process_item()` — vLLM enriched mit geopolitischem Kontext.

### Neo4j-Erweiterung

Statische `NuclearTestSite`-Nodes (einmalig beim ersten Run erstellt):

```cypher
MERGE (s:NuclearTestSite {name: $name})
SET s.latitude = $lat, s.longitude = $lon
```

Events nahe Test-Sites bekommen eine `NEAR_TEST_SITE`-Relationship. Der USGS-Collector schreibt diese als eigenes Neo4j-Statement **im selben Transaction-Batch** nach `process_item()`. Matching läuft über den Document-Node (der die `url` als stabile Property hat):

```cypher
MATCH (d:Document {url: $usgs_url})-[:DESCRIBES]->(e:Event)
MATCH (s:NuclearTestSite {name: $site_name})
MERGE (e)-[:NEAR_TEST_SITE {distance_km: $dist, concern_score: $score, concern_level: $level}]->(s)
```

Damit ist das Linking unabhängig von Event-Title-Matching und nutzt den stabilen `Document.url` → `DESCRIBES` → `Event`-Pfad.

### Qdrant-Payload

```python
{
    "source": "usgs",
    "title": str,               # "M6.2 - 45km NE of Punggye-ri"
    "url": str,                 # USGS event page
    "usgs_id": str,
    "magnitude": float,
    "depth_km": float,
    "place": str,
    "latitude": float,
    "longitude": float,
    "event_time": str,          # ISO datetime
    "nearest_test_site": str | None,
    "distance_km": float | None,
    "concern_score": float | None,
    "concern_level": str | None, # "critical", "elevated", "moderate", None
}
```

### Scheduler

`IntervalTrigger(hours=6)`.

---

## 6. Collector: Military Aircraft (adsb.fi + OpenSky Fallback)

### Datenwert

Military Aircraft Detection über ICAO Hex-Range-Filtering. Erkennt Deployment-Muster, Surge-Aktivität, Base-Posture-Changes.

### Primary: adsb.fi

```
GET https://api.adsb.fi/v2/mil
```

Kein Auth, kein Rate-Limit. Dedizierter Military-Endpoint — liefert nur Militärflugzeuge.

### Fallback: OpenSky

Nur wenn adsb.fi ausfällt. OAuth2 Client Credentials:

```
POST https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token
Body: grant_type=client_credentials, client_id={id}, client_secret={secret}
```

Region-Queries:
```python
OPENSKY_REGIONS = {
    "pacific": {"lamin": 10, "lamax": 46, "lomin": 107, "lomax": 143},
    "western": {"lamin": 13, "lamax": 85, "lomin": -10, "lomax": 57},
}
```

### ICAO Hex-Range Filter

Für Enrichment der adsb.fi-Daten (Branch-Zuordnung):

```python
MILITARY_ICAO_RANGES = {
    "USAF":   [("ADF7C8", "AFFFFF")],
    "RAF":    [("400000", "40003F"), ("43C000", "43CFFF")],
    "FAF":    [("3AA000", "3AFFFF"), ("3B7000", "3BFFFF")],
    "GAF":    [("3EA000", "3EBFFF"), ("3F4000", "3FBFFF")],
    "IAF":    [("738A00", "738BFF")],
    "NATO":   [("4D0000", "4D03FF")],
}

def identify_branch(icao24: str) -> str | None:
    hex_val = int(icao24, 16)
    for branch, ranges in MILITARY_ICAO_RANGES.items():
        for start, end in ranges:
            if int(start, 16) <= hex_val <= int(end, 16):
                return branch
    return None
```

### Pipeline

**Kein `process_item()`** — die Daten sind strukturiert (ADS-B Transponder), kein Fließtext. Direkter Neo4j-Write + Qdrant-Upsert.

### Neo4j Schema

```cypher
MERGE (a:MilitaryAircraft {icao24: $icao24})
SET a.callsign = $callsign,
    a.military_branch = $branch,
    a.last_seen = $timestamp

MERGE (l:Location {name: $location_name})
SET l.latitude = $lat, l.longitude = $lon

MERGE (a)-[:SPOTTED_AT {timestamp: $timestamp, altitude: $alt, velocity: $vel}]->(l)
```

Location-Name wird aus einer statischen Regions-Liste abgeleitet (gleiche Bounding Boxes wie FIRMS: "ukraine", "iran", etc. + "pacific", "western" aus OpenSky). Kein Reverse-Geocoding.

### Dedup

Content-Hash: `{icao24}|{timestamp_rounded_to_15min}` — ein Aircraft pro 15-Minuten-Fenster.

### Qdrant-Payload

```python
{
    "source": "military_aircraft",
    "title": str,               # "USAF aircraft {callsign} over {region}"
    "url": str,                 # adsb.fi link
    "icao24": str,
    "callsign": str,
    "origin_country": str,
    "military_branch": str | None,
    "latitude": float,
    "longitude": float,
    "altitude_m": float,
    "velocity_ms": float,
    "on_ground": bool,
    "heading": float,
}
```

### Scheduler

`IntervalTrigger(minutes=15)`.

### Config

```python
opensky_client_id: str = ""      # .env: OPENSKY_CLIENT_ID
opensky_client_secret: str = ""  # .env: OPENSKY_CLIENT_SECRET
```

---

## 7. Collector: OFAC Sanctions (US Treasury)

### Datenwert

Entity-Resolution-Anker für den gesamten Knowledge Graph. Wenn eine sanktionierte Entity in News, ACLED oder GDELT auftaucht → sofortiges Flag. Die Alias-Listen und ID-Nummern (IMO für Schiffe, Passport-Nummern) ermöglichen automatisches Matching.

### Endpoints

```
SDN:          https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/sdn_advanced.xml
Consolidated: https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/cons_advanced.xml
```

Keine Auth.

### XML-Parsing

OFAC Advanced XML Schema — verschachtelte Struktur:

```xml
<sdnList>
  <sdnEntry>
    <uid>12345</uid>
    <sdnType>Individual|Entity|Vessel|Aircraft</sdnType>
    <lastName>DOE</lastName>
    <firstName>John</firstName>
    <programList><program>SDGT</program></programList>
    <akaList>
      <aka><lastName>SMITH</lastName><type>a.k.a.</type></aka>
    </akaList>
    <idList>
      <id><idType>Passport</idType><idNumber>X123456</idNumber><idCountry>IR</idCountry></id>
      <id><idType>IMO Number</idType><idNumber>9123456</idNumber></id>
    </idList>
    <addressList>
      <address><country>Iran</country><city>Tehran</city></address>
    </addressList>
  </sdnEntry>
</sdnList>
```

Parser extrahiert:
- Entity: uid, type, full_name (constructed), nationality
- Programs: liste von Sanctions-Programmen (SDGT, IRAN, UKRAINE-EO13661, etc.)
- Aliases: alle a.k.a. / f.k.a. Einträge
- Identifiers: Passport, IMO, Tax ID, etc. mit Country
- Addresses: Country + City

### Pipeline

**Kein `process_item()`** — Daten sind bereits strukturiert. Kein LLM-Extraction nötig.

### Neo4j Schema

Eigene Cypher-Templates (deterministic, kein LLM-generiertes Cypher):

```cypher
-- Entity
MERGE (e:SanctionedEntity {ofac_id: $uid})
SET e.name = $full_name,
    e.type = $sdn_type,
    e.updated_at = $timestamp

-- Program
MERGE (p:SanctionsProgram {name: $program})
MERGE (e)-[:SANCTIONED_UNDER]->(p)

-- Alias
MERGE (a:Alias {name: $alias_name})
MERGE (e)-[:HAS_ALIAS]->(a)

-- Identifier
MERGE (i:Identifier {type: $id_type, value: $id_value})
SET i.country = $id_country
MERGE (e)-[:HAS_ID]->(i)
```

### Entity-Resolution Hook

Beim OFAC-Ingest wird für jeden Entity-Namen + Aliases ein Qdrant-Embedding erzeugt. Dadurch kann der ReAct-Agent bei Qdrant-Suche automatisch sanktionierte Entities finden, wenn ähnliche Namen in News auftauchen.

Embedding-Text: `"{name} | AKA: {alias1}, {alias2} | Programs: {prog1}, {prog2}"`.

### Dedup

Content-Hash: `ofac|{uid}`. Bei Re-Ingest wird die Entity aktualisiert (MERGE), nicht dupliziert.

### Qdrant-Payload

```python
{
    "source": "ofac",
    "title": str,               # "OFAC SDN: {name} ({type})"
    "url": str,                 # Treasury deep link
    "ofac_id": str,
    "entity_type": str,         # "Individual", "Entity", "Vessel", "Aircraft"
    "programs": list[str],      # ["SDGT", "IRAN"]
    "aliases": list[str],
    "identifiers": list[dict],  # [{"type": "IMO", "value": "9123456", "country": "IR"}]
    "addresses": list[dict],    # [{"country": "Iran", "city": "Tehran"}]
}
```

### Scheduler

`CronTrigger(hour=3, minute=30, timezone="UTC")` — täglich nach dem TLE-Update (03:00 UTC).

---

## 8. Config-Erweiterungen

Neue Felder in `services/data-ingestion/config.py`:

```python
# ACLED
acled_email: str = ""
acled_password: str = ""

# NASA FIRMS
nasa_earthdata_key: str = ""

# OpenSky (Fallback für Military Aircraft)
opensky_client_id: str = ""
opensky_client_secret: str = ""

# UCDP (optional)
ucdp_access_token: str = ""

# Collector Intervals (overridable)
acled_interval_hours: int = 6
ucdp_interval_hours: int = 12
firms_interval_hours: int = 2
usgs_interval_hours: int = 6
military_interval_minutes: int = 15
```

### .env.example Ergänzungen

```bash
# Hugin P0 Collectors
ACLED_EMAIL=
ACLED_PASSWORD=
NASA_EARTHDATA_KEY=
OPENSKY_CLIENT_ID=
OPENSKY_CLIENT_SECRET=
UCDP_ACCESS_TOKEN=
```

---

## 9. Scheduler-Registrierung

Neue Jobs in `services/data-ingestion/scheduler.py`:

```python
settings = Settings()

# ACLED — default 6 Stunden
scheduler.add_job(run_acled_collector,
                  IntervalTrigger(hours=settings.acled_interval_hours),
                  id="acled", coalesce=True, max_instances=1)

# UCDP — default 12 Stunden
scheduler.add_job(run_ucdp_collector,
                  IntervalTrigger(hours=settings.ucdp_interval_hours),
                  id="ucdp", coalesce=True, max_instances=1)

# FIRMS — default 2 Stunden
scheduler.add_job(run_firms_collector,
                  IntervalTrigger(hours=settings.firms_interval_hours),
                  id="firms", coalesce=True, max_instances=1)

# USGS Nuclear — default 6 Stunden
scheduler.add_job(run_usgs_collector,
                  IntervalTrigger(hours=settings.usgs_interval_hours),
                  id="usgs_nuclear", coalesce=True, max_instances=1)

# Military Aircraft — default 15 Minuten
scheduler.add_job(run_military_collector,
                  IntervalTrigger(minutes=settings.military_interval_minutes),
                  id="military_aircraft", coalesce=True, max_instances=1)

# OFAC Sanctions — täglich 03:30 UTC (Cron, nicht interval-overridable)
scheduler.add_job(run_ofac_collector,
                  CronTrigger(hour=3, minute=30, timezone="UTC"),
                  id="ofac", coalesce=True, max_instances=1)
```

---

## 10. Neo4j Schema — Zusammenfassung Erweiterungen

### Neue Node-Labels

| Label | Quelle | Key Properties |
|-------|--------|----------------|
| `SanctionedEntity` | OFAC | ofac_id, name, type |
| `SanctionsProgram` | OFAC | name |
| `Alias` | OFAC | name |
| `Identifier` | OFAC | type, value, country |
| `NuclearTestSite` | USGS | name, latitude, longitude |
| `MilitaryAircraft` | adsb.fi/OpenSky | icao24, callsign, military_branch |
| _(FIRMS nutzt Standard-Event via `process_item()` mit `possible_explosion` Property)_ | | |

### Neue Relationships

| Relationship | Von → Nach | Properties |
|-------------|-----------|------------|
| `SANCTIONED_UNDER` | SanctionedEntity → SanctionsProgram | — |
| `HAS_ALIAS` | SanctionedEntity → Alias | — |
| `HAS_ID` | SanctionedEntity → Identifier | — |
| `NEAR_TEST_SITE` | Event → NuclearTestSite | distance_km, concern_score |
| `SPOTTED_AT` | MilitaryAircraft → Location | timestamp, altitude, velocity |

### Bestehende Labels (weiter genutzt)

`Document`, `Entity`, `Event`, `Location` — werden von ACLED, UCDP, FIRMS, USGS über den Standard-`process_item()`-Pfad befüllt.

---

## 11. Testing

### BaseCollector Tests (`tests/test_base_collector.py`)

- `test_ensure_collection_creates_if_missing`
- `test_ensure_collection_skips_if_exists`
- `test_embed_calls_tei`
- `test_content_hash_deterministic`
- `test_dedup_check_returns_true_for_existing`
- `test_dedup_check_returns_false_for_new`
- `test_batch_upsert_empty_list_noop`

### Per-Collector Tests

Jeder Collector bekommt:

1. **Happy-Path Test** — Gemockter HTTP-Response → `collect()` → prüfe Qdrant-Upsert-Calls
2. **Dedup Test** — Gleicher Content zweimal → nur ein Upsert
3. **Auth Failure Test** — 401 → Token-Refresh → Retry (ACLED, OpenSky)
4. **Payload Validation Test** — Response-Parsing in Pydantic Model
5. **Rate Limit Test** — 429 → Backoff + Retry (FIRMS, ACLED)
6. **Empty Response Test** — Leere API-Antwort → graceful exit, keine Exceptions

### OFAC-spezifisch

- **XML Parse Test** — SDN Advanced XML → korrekte Entity-Extraktion
- **Alias Matching Test** — Alle AKA-Varianten werden extrahiert
- **IMO Identifier Test** — Vessel-IDs korrekt geparst

### USGS-spezifisch

- **Concern Score Test** — Bekannte Werte für verschiedene Distanzen/Tiefen/Magnituden
- **No-Match Test** — Erdbeben weit weg von Test-Sites → kein Enrichment

### FIRMS-spezifisch

- **Explosion Heuristic Test** — `frp=90, brightness=390` → `possible_explosion=True`
- **Multi-Satellite Dedup Test** — Gleicher Hotspot von 2 Satelliten → nur ein Point

### Mocking

Alle HTTP-Calls über `respx` (httpx-Mocking-Library). Qdrant über `unittest.mock`. Kein echter Netzwerk-Zugriff in Tests.

---

## 12. Implementierungs-Reihenfolge

1. **BaseCollector** — Fundament für alle anderen
2. **ACLED** — höchster Intelligence-Wert, OAuth als komplexester Auth-Flow
3. **FIRMS** — zweithöchster Wert, Explosion-Heuristik
4. **OFAC** — XML-Parsing, eigenes Neo4j-Schema
5. **USGS** — einfachster Collector, Nuclear-Enrichment als Bonus
6. **UCDP** — Version-Discovery-Logik
7. **Military Aircraft** — adsb.fi Primary + OpenSky Fallback

---

## Nicht in Scope

- **ACLED + FIRMS Cross-Korrelation** — eigenes Feature nach dieser Spec
- **Migration bestehender Collectors auf BaseCollector** — kein Refactoring ohne Feature-Wert
- **Frontend-Visualisierung** der neuen Daten — separate Spec
- **ReAct-Agent-Tools** für die neuen Quellen — separate Spec
- **Alerting/Notification** bei critical Events — separate Spec
