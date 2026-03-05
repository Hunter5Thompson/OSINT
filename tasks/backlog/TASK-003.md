# TASK-003: Flight Data Proxy (OpenSky + adsb.fi)

## Service/Modul
services/backend/app/routers/flights.py + services/backend/app/services/flight_service.py

## Akzeptanzkriterien
- [ ] GET /api/v1/flights → list[Aircraft] (Pydantic model)
- [ ] OpenSky API als Primary Source, adsb.fi als Fallback
- [ ] Redis Cache mit 10s TTL
- [ ] Graceful degradation: leere Liste wenn beide APIs down
- [ ] Rate-Limiting-Awareness: 10s Cooldown für OpenSky
- [ ] GET /api/v1/flights/military → gefiltert nach ICAO Military Prefix DB

## Tests (VOR Implementierung schreiben)
- [ ] tests/unit/test_flight_service.py (Parsing, Fallback-Logic, Cache)
- [ ] tests/unit/test_flight_models.py (Pydantic Validation)
- [ ] tests/integration/test_flights_api.py (Mock-Responses)

## Fixtures
- tests/fixtures/opensky_response.json
- tests/fixtures/adsbfi_response.json

## Dependencies
- Blocked by: TASK-002
- Blocks: TASK-009 (Frontend Flight Layer)

## Documentation
- OpenSky REST API: https://openskynetwork.github.io/opensky-api/rest.html
- adsb.fi API: https://api.adsb.fi/

## Session-Notes
(noch keine Sessions)
