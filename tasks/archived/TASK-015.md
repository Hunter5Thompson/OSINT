# TASK-015: Hugin — Sentinel-2 Collector Modul

## Service/Modul
services/data-ingestion/feeds/sentinel_collector.py

## Kontext
Hugin soll Sentinel-2 Satellitenbilder automatisch nach AOI (Area of Interest = aktive
Hotspots) abfragen und Thumbnails + Metadata für die Munin-Analyse bereitstellen.

**Primär-Endpoint: Element84 STAC** (AWS Open Data Mirror, kein Account, kein Auth)
Gleiche ESA-Daten wie CDSE, aber produktionsstabiler — Live-Test 2026-03-29 hat gezeigt
dass catalogue.dataspace.copernicus.eu den Request nicht beantwortet (Timeout),
während Element84 sofort antwortet.

## Architektur-Entscheidung: Endpoint-Strategie

| Endpoint | Auth | Catalog | Thumbnails | Full COG | Status |
|---|---|---|---|---|---|
| **Element84 STAC** (primary) | Nein | ✓ | ✓ (public S3) | ✓ (public S3) | **Produktiv** |
| CDSE catalogue.dataspace.copernicus.eu | Nein | ✗ (Timeout 2026-03-29) | - | - | Degraded |
| CDSE S3 Direct | Ja (S3-Keys) | - | - | ✓ | Account nötig |

Element84 STAC URL: `https://earth-search.aws.element84.com/v1`
Collection für S-2 L2A: `sentinel-2-c1-l2a` (Collection 1, aktuelle Generation)

## Architektur-Entscheidung: S-1 (SAR) vs. S-2 (Optical)

| Typ | Pro | Contra |
|---|---|---|
| **Sentinel-2 Optical** | Kein Auth, Public S3, RGB+NIR, 10m Auflösung, einfach | Wolkenabhängig |
| **Sentinel-1 SAR** | Wetterunabhängig, 24/7, Schiffs-/Fahrzeugdetektion | SAR-Prozessierung komplex, Auth nötig |

**Entscheidung:** Phase 1+2 = S-2 via Element84 (kein Account nötig). S-1 = Phase 3.

## Live-Test Ergebnisse (2026-03-29)

Getestet mit AOI Gaza (34.1°E–34.6°E, 31.2°N–31.6°N):

```
Szene: S2B_T36RXV_20260320T082938_L2A
  Datum:    2026-03-20T08:29:38 UTC
  Cloud:    24%
  Platform: sentinel-2b
  Assets:   red, green, blue, visual, nir, swir22, rededge1-3, scl, cloud, snow, ...
  Thumbnail: 37 KB JPEG ✓ (visuell verifiziert — Küstenlinie Gaza sichtbar)
  S3 URL:   https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/...
```

Revisit-Rate über Gaza: ~2-3 Tage (Sentinel-2A + 2B + 2C im Orbit).

## Akzeptanzkriterien

### Phase 1 — Catalog Search + Thumbnail (kein Auth)
- [ ] `pystac-client` verbindet mit `earth-search.aws.element84.com/v1`
- [ ] Funktion `query_scenes(lat, lon, radius_km, max_cloud_pct, days_back)` → `list[SentinelScene]`
- [ ] Filter: `eo:cloud_cover < max_cloud_pct`, Collection `sentinel-2-c1-l2a`
- [ ] Fallback-Logik: wenn `days_back=7` keine klare Szene → automatisch auf 30 Tage erweitern
- [ ] Integration mit Hotspot-Liste: Auto-Query für alle aktiven Hotspots (CRITICAL + HIGH)
- [ ] APScheduler Job: täglich 06:00 UTC, Ergebnisse in Redis (TTL 24h)

### Phase 2 — Thumbnail Download + Cache
- [ ] Download PVI Thumbnail (JPEG, ~10–40 KB) direkt von public S3
- [ ] Thumbnails in `data/sentinel-thumbs/{scene_id}.jpg` ablegen
- [ ] `GET /api/v1/sentinel/scenes?hotspot_id=xyz` → Liste von SentinelScene
- [ ] `GET /api/v1/sentinel/thumbnail/{scene_id}` → JPEG aus lokalem Cache
- [ ] Frontend: Sentinel-Layer im OperationsPanel, Klick auf Hotspot → neueste klare Szene

### Phase 3 — S-1 SAR + Full COG (spätere Iteration)
- [ ] Sentinel-1 GRD über maritimen Hotspots (CDSE S3 mit Account)
- [ ] COG-Zugriff via byte-range requests (kein vollständiger Download)

## Pydantic Model

```python
class SentinelScene(BaseModel):
    scene_id: str                    # z.B. "S2B_T36RXV_20260320T082938_L2A"
    collection: Literal["sentinel-2-c1-l2a", "sentinel-1-grd"]
    platform: str                    # "sentinel-2a" | "sentinel-2b" | "sentinel-2c"
    acquired_at: datetime
    cloud_cover_pct: float | None
    footprint_bbox: tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)
    thumbnail_url: str
    thumbnail_local: str | None      # Lokaler Pfad nach Download
    stac_item_url: str               # Direktlink zum STAC Item
    hotspot_ids: list[str]           # Welche Hotspots liegen im Footprint
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
```

## Tests (VOR Implementierung schreiben)

```
data-ingestion/tests/
├── unit/
│   ├── test_sentinel_scene_model.py         # Pydantic Validation
│   ├── test_aoi_to_bbox.py                  # (lat,lon,radius) → BBox-Konvertierung
│   └── test_cloud_fallback_logic.py         # 7-Tage-Fallback auf 30 Tage
├── integration/
│   └── test_element84_stac_live.py          # Echter API Call (mark: integration)
│                                            # Referenz-AOI: Gaza (34.1,31.2,34.6,31.6)
│                                            # Erwartung: ≥1 Szene in letzten 30 Tagen
```

## Credentials
- **Phase 1+2: Keine nötig** (Element84 public S3)
- Phase 3 (CDSE S3): `CDSE_S3_ACCESS_KEY`, `CDSE_S3_SECRET_KEY` via CDSE Dashboard

## Dependencies
- Blocked by: TASK-001 (Repo Setup)
- Blocks: TASK-013 (Integration Test — Sentinel als optionaler Layer)
- Neue Python-Dependencies: `pystac-client`, `shapely`

## Documentation
- Element84 STAC: https://earth-search.aws.element84.com/v1
- pystac-client: https://pystac-client.readthedocs.io/
- CDSE Docs (Fallback): https://documentation.dataspace.copernicus.eu/APIs/STAC.html

## Session-Notes

**Status 2026-03-29: GETESTET — sentinel_collector.py NICHT implementiert**
Phase 1 Akzeptanzkriterien: alle ❌ offen (keine Implementierung, nur Live-Test)

2026-03-29: Task erstellt + Live-Test durchgeführt.
  - catalogue.dataspace.copernicus.eu: Timeout, nicht nutzbar
  - Element84 STAC: sofort erreichbar, 5 Gaza-Szenen in Feb-März 2026 gefunden
  - Thumbnail S2B_T36RXV_20260320 (24% cloud) heruntergeladen + visuell verifiziert ✓
  - Küstenlinie Gaza, Negev, Sinai klar erkennbar
  - Primär-Endpoint auf Element84 umgestellt, CDSE als Fallback degradiert
