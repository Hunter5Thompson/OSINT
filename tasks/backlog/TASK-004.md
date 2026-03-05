# TASK-004: Earthquake Proxy (USGS GeoJSON)

## Service/Modul
services/backend/app/routers/earthquakes.py

## Akzeptanzkriterien
- [ ] GET /api/v1/earthquakes → list[Earthquake]
- [ ] USGS GeoJSON Feed M4.5+ (7 Tage)
- [ ] Redis Cache 5min TTL
- [ ] Pydantic Model mit magnitude, depth, coordinates, tsunami flag

## Dependencies
- Blocked by: TASK-002
- Blocks: TASK-009

## Documentation
- USGS API: https://earthquake.usgs.gov/fdsnws/event/1/

## Session-Notes
(noch keine Sessions)
