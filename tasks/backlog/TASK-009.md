# TASK-009: CesiumJS Globe + Google 3D Tiles + Flight Layer Frontend

## Service/Modul
services/frontend/src/components/globe/ + services/frontend/src/components/layers/

## Akzeptanzkriterien
- [ ] CesiumJS Viewer initialisiert mit Google Photorealistic 3D Tiles
- [ ] Fallback auf Cesium World Terrain + OSM Buildings wenn kein API Key
- [ ] Camera Controls: Drag-Rotate, Scroll-Zoom, Double-Click-Fly-To
- [ ] FlightLayer: BillboardCollection mit >5000 Entities bei 60 FPS
- [ ] Dead-Reckoning: Positionen zwischen API-Updates interpoliert
- [ ] Heading-Rotation auf Billboard-Icons
- [ ] Click-to-Track: Klick auf Flugzeug → Kamera folgt
- [ ] ESC: Tracking unlock
- [ ] SatelliteLayer: SGP4 Propagation via satellite.js, Orbit-Pfade als PolylineCollection
- [ ] EarthquakeLayer: Pulsing PointPrimitives, magnitude-proportional

## Tests (VOR Implementierung schreiben)
- [ ] tests/e2e/test_globe_loads.spec.ts (Playwright: Globe sichtbar)
- [ ] tests/e2e/test_flight_layer.spec.ts (Playwright: Flugzeuge erscheinen)
- [ ] src/components/layers/__tests__/FlightLayer.test.tsx (Unit: Data Parsing)

## Dependencies
- Blocked by: TASK-001 (Repo), TASK-003 (Flight API)
- Blocks: TASK-010 (GLSL Shaders), TASK-011 (Tactical UI)

## Documentation
- Context7: `/cesiumgs/cesium` → "Google 3D Tiles, BillboardCollection, PointPrimitiveCollection, CallbackProperty"
- Context7: `/websites/cesium_learn_cesiumjs` → "Quickstart, camera controls"
- Context7: `/shashwatak/satellite-js` → "SGP4 propagation from TLE"
- CesiumJS + React Pattern: https://cesium.com/learn/cesiumjs-learn/cesiumjs-quickstart/

## Session-Notes
(noch keine Sessions)
