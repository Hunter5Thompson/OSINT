# ACLED + FIRMS Cross-Korrelation — Design Spec

> Batch-Job der FIRMS-Thermal-Anomalien mit ACLED-Konfliktereignissen korreliert. FRP-Spike + ACLED-Battle im selben 50km-Radius und ±1-Tag-Fenster = high-confidence verifiziertes Event. Ergebnis wird als `CORROBORATED_BY`-Relationship in Neo4j gespeichert.

**Datum:** 2026-04-09
**Status:** Draft
**Abhängigkeiten:** ACLED Collector, FIRMS Collector (beide merged in Hugin P0)

---

## 1. Konzept

Ein periodischer Batch-Job scannt neue FIRMS-Hotspots mit `possible_explosion=true` und sucht in Qdrant nach ACLED-Events im selben Raum-Zeit-Fenster. Treffer bekommen eine gewichtete `CORROBORATED_BY`-Relationship in Neo4j.

**Warum Batch und nicht Stream:** ACLED hat 1-2 Tage Lag, FIRMS ~3h. Echtzeit-Korrelation bringt keinen Mehrwert bei diesen Quell-Latenzen. Ein Job alle 2h nach dem FIRMS-Run ist ausreichend.

**Warum Neo4j und nicht Qdrant:** Die Korrelation ist eine Beziehung zwischen zwei Events, kein eigenständiges Dokument. Graph-Traversal ("Welche ACLED-Battles haben Satellitenbestätigung?") ist der primäre Use-Case.

---

## 2. Datenfluss

```
FIRMS Collector (alle 2h)
  ↓ fertig
Correlation Job startet (5 min versetzt)
  ↓
Qdrant Scroll: FIRMS-Events
  Filter: source=firms, possible_explosion=true, ingested_at > last_run
  ↓
Für jeden FIRMS-Hit (lat, lon, acq_date):
  ↓
  Qdrant Scroll: ACLED-Candidates
    Filter: source=acled,
            latitude ∈ [firms_lat - 0.5°, firms_lat + 0.5°],
            longitude ∈ [firms_lon - 0.5°, firms_lon + 0.5°]
    ↓
  Application-Level Filter:
    haversine(firms, acled) ≤ 50km
    |acled.event_date - firms.acq_date| ≤ 1 day
    ↓
  Confidence-Score berechnen
    ↓
  Score ≥ min_score (0.3)?
    ↓ ja
  Neo4j: MERGE CORROBORATED_BY Relationship
```

### Last-Run Tracking

Redis Key `correlation:last_run` speichert den ISO-Timestamp des letzten Laufs. Beim Start werden nur FIRMS-Events seit diesem Zeitpunkt verarbeitet. Beim ersten Run: alle FIRMS-Events der letzten 7 Tage.

---

## 3. Qdrant-Abfragen

### FIRMS-Kandidaten (neue Explosions-Verdachtsfälle)

```python
from qdrant_client.models import Filter, FieldCondition, MatchValue, Range

firms_filter = Filter(must=[
    FieldCondition(key="source", match=MatchValue(value="firms")),
    FieldCondition(
        key="possible_explosion",
        match=MatchValue(value=True),
    ),
    FieldCondition(
        key="ingested_at",
        range=Range(gte=last_run_iso),
    ),
])
```

### ACLED-Candidates (räumliche Vorfilterung)

Bbox-Filter als Grobfilter, danach Haversine für exakte Distanz. Latitude-Delta ist fix ±0.5° (~55km). Longitude-Delta wird breitengrad-korrigiert (`0.5 / cos(lat)`) damit der Bbox bei hohen Breitengraden (Ukraine ~50°N) nicht zu eng wird:

```python
import math

lat_delta = 0.5
lon_delta = 0.5 / max(math.cos(math.radians(firms_lat)), 0.1)

acled_filter = Filter(must=[
    FieldCondition(key="source", match=MatchValue(value="acled")),
    FieldCondition(
        key="latitude",
        range=Range(gte=firms_lat - lat_delta, lte=firms_lat + lat_delta),
    ),
    FieldCondition(
        key="longitude",
        range=Range(gte=firms_lon - lon_delta, lte=firms_lon + lon_delta),
    ),
])
```

**Keine Zeitfilterung in Qdrant:** ACLED hat `event_date` als String (YYYY-MM-DD) im Payload, nicht als numerischen Range-Wert. Zeitfilterung erfolgt application-seitig nach dem Scroll.

---

## 4. Haversine-Filter

Wiederverwendung der `haversine_km()`-Funktion aus `feeds/usgs_collector.py`. Import oder Extraktion in ein Shared-Modul (`feeds/geo.py`).

```python
from feeds.geo import haversine_km

dist = haversine_km(firms_lat, firms_lon, acled_lat, acled_lon)
if dist > settings.correlation_radius_km:
    continue  # Zu weit weg
```

### Zeitfilterung

```python
from datetime import date

firms_date = date.fromisoformat(firms_acq_date)
acled_date = date.fromisoformat(acled_event_date)
days_diff = abs((firms_date - acled_date).days)

if days_diff > settings.correlation_time_window_days:
    continue  # Außerhalb Zeitfenster
```

---

## 5. Confidence-Score

```python
def correlation_score(
    distance_km: float,
    days_diff: int,
    possible_explosion: bool,
    acled_event_type: str,
    firms_confidence: str,
) -> float:
    """Berechne Korrelations-Confidence zwischen FIRMS und ACLED Event.

    Returns: 0.0–1.0 Score.
    """
    # Distance: 0km = 1.0, 50km = 0.0 (linear)
    dist_score = max(0.0, 1.0 - distance_km / 50.0)

    # Time: same day = 1.0, ±1 day = 0.5
    time_score = 1.0 if days_diff == 0 else 0.5

    # Base = distance × time (0.0–1.0)
    base = dist_score * time_score

    # Bonuses (additive, capped at 1.0)
    bonus = 0.0
    if possible_explosion:
        bonus += 0.3
    if acled_event_type == "Explosions/Remote violence":
        bonus += 0.2
    if firms_confidence == "high":
        bonus += 0.1

    return min(1.0, round(base + bonus, 2))
```

### Score-Ranges

| Score | Bezeichnung | Bedeutung |
|-------|-------------|-----------|
| ≥ 0.8 | high | Sehr wahrscheinlich dasselbe Event |
| ≥ 0.5 | medium | Plausible Korrelation |
| 0.3–0.5 | low | Weit entfernt oder zeitversetzt |
| < 0.3 | — | Nicht gespeichert (unter `correlation_min_score`) |

---

## 6. Neo4j Schema

### Relationship

```cypher
MATCH (d1:Document {url: $acled_url})-[:DESCRIBES]->(e1:Event)
MATCH (d2:Document {url: $firms_url})-[:DESCRIBES]->(e2:Event)
MERGE (e1)-[r:CORROBORATED_BY]->(e2)
SET r.distance_km = $dist,
    r.days_diff = $days,
    r.confidence = $score,
    r.correlation_time = $timestamp
```

**Richtung:** ACLED-Event → `CORROBORATED_BY` → FIRMS-Event. Der Konflikt wird durch den Satelliten bestätigt, nicht umgekehrt.

**MERGE statt CREATE:** Idempotent — bei erneutem Run wird die bestehende Relationship aktualisiert (Score könnte sich ändern wenn neue ACLED-Daten reinkommen).

### Beispiel-Query für den ReAct-Agent

```cypher
MATCH (e:Event)-[r:CORROBORATED_BY]->(f:Event)
WHERE r.confidence >= 0.5
RETURN e.title, f.title, r.distance_km, r.confidence
ORDER BY r.confidence DESC
LIMIT 20
```

---

## 7. Shared Geo-Modul

`haversine_km()` wird aktuell in `usgs_collector.py` definiert. Um Duplikation zu vermeiden:

Extraktion in `services/data-ingestion/feeds/geo.py`:

```python
"""Shared geospatial utilities."""

import math


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Great-circle distance in km between two WGS-84 points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
```

`usgs_collector.py` wird auf `from feeds.geo import haversine_km` umgestellt.

---

## 8. Config-Erweiterungen

Neue Felder in `services/data-ingestion/config.py`:

```python
# FIRMS-ACLED Correlation
correlation_radius_km: float = 50.0
correlation_time_window_days: int = 1
correlation_min_score: float = 0.3
correlation_interval_hours: int = 2
```

---

## 9. Scheduler-Registrierung

```python
scheduler.add_job(
    run_correlation_job,
    trigger=IntervalTrigger(
        hours=settings.correlation_interval_hours,
    ),
    id="firms_acled_correlation",
    name="FIRMS-ACLED Correlation",
    replace_existing=True,
)
```

Nicht in `initial_tasks` — Korrelation braucht bestehende Daten, macht beim ersten Start keinen Sinn.

---

## 10. Dateien

| Datei | Verantwortung |
|-------|---------------|
| `services/data-ingestion/feeds/geo.py` | Shared haversine_km() |
| `services/data-ingestion/feeds/correlation_job.py` | Batch-Korrelationslogik |
| `services/data-ingestion/tests/test_geo.py` | Geo-Utility Tests |
| `services/data-ingestion/tests/test_correlation_job.py` | Korrelations-Tests |

Modifiziert:
| `services/data-ingestion/feeds/usgs_collector.py` | Import von geo.py statt eigener haversine |
| `services/data-ingestion/config.py` | Neue correlation_* Settings |
| `services/data-ingestion/scheduler.py` | Neuer Job |

---

## 11. Testing

### test_geo.py

- `test_haversine_known_distance` — NYC→LA ≈ 3944km
- `test_haversine_same_point` — 0.0km
- `test_haversine_short_distance` — <1km Accuracy

### test_correlation_job.py

- `test_correlation_score_close_same_day_explosion` — 5km, day 0, explosion → ≥ 0.8
- `test_correlation_score_far_next_day` — 45km, day 1 → < 0.5
- `test_correlation_score_boundary` — genau 50km → dist_score = 0.0
- `test_correlation_score_capped_at_1` — maximale Bonuses → 1.0
- `test_below_min_score_not_stored` — Score < 0.3 → kein Neo4j-Write
- `test_bbox_filter_construction` — Qdrant-Filter hat korrekte ±0.5° Ranges
- `test_time_filter_rejects_old` — ACLED 3 Tage alt → rausgefiltert
- `test_dedup_merge_idempotent` — Gleiche Korrelation zweimal → eine Relationship
- `test_first_run_uses_7_day_window` — Kein `last_run` Key → 7 Tage Lookback

---

## 12. Nicht in Scope

- **Alerting/Notification** bei high-confidence Korrelation — eigenes Feature
- **Frontend-Visualisierung** der Korrelationen auf dem Globe — eigenes Feature
- **Andere Quellen-Paare** (z.B. UCDP + FIRMS) — kann später ergänzt werden, gleiche Architektur
- **ReAct-Agent-Tool** — Agent findet Korrelationen über bestehende Graph-Query-Tools
