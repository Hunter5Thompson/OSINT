# TASK-005: Satellite TLE Proxy (CelesTrak)

## Service/Modul
services/backend/app/routers/satellites.py

## Akzeptanzkriterien
- [ ] GET /api/v1/satellites → list[Satellite] (TLE data)
- [ ] CelesTrak GP Data als Source (aktive Satelliten ~9000)
- [ ] Redis Cache 1h TTL (TLEs ändern sich langsam)
- [ ] Kategorisierung: military, gps, weather, active, etc.

## Dependencies
- Blocked by: TASK-002
- Blocks: TASK-009

## Documentation
- CelesTrak: https://celestrak.org/NORAD/documentation/gp-data-formats.php
- Context7: `/shashwatak/satellite-js` → "TLE parsing"
