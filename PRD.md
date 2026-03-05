<!-- manifest: project=WorldView | doc_version=1.0 | compatible_with=arch:1.0,feat:1.0 | updated=2026-03-05 -->

# WorldView — Product Requirements Document

## Summary (max. 500 Token)

WorldView ist eine lokal ausführbare Tactical Intelligence Platform, die Echtzeit-Geodaten (Flüge, Satelliten, Erdbeben, Schiffe, Verkehr, CCTV) auf einem 3D CesiumJS-Globe mit Google Photorealistic 3D Tiles fusioniert. Ein FastAPI-Backend proxied externe Datenfeeds und betreibt ein LangGraph-basiertes Multi-Agent RAG-System (Ollama/vLLM auf RTX 5090) für KI-gestützte Intelligence-Analysen. GLSL Post-Processing (CRT, Night Vision, FLIR) und ein taktisches C2-Interface runden das System ab. Zielgruppe: Einzelentwickler/Analyst mit On-Premise GPU-Stack.

---

## 1. Projektvision

WorldView löst das Problem, dass taktische Lagebilder entweder proprietär und teuer (Palantir Gotham) oder fragmentiert über Dutzende Einzelquellen verstreut sind. Die Lösung fusioniert öffentlich zugängliche Echtzeit-Datenfeeds auf einem photorealistischen 3D-Globus mit KI-gestützter Intelligence-Analyse — vollständig lokal ausführbar auf Consumer-GPU-Hardware.

**Mehrwert:** Palantir-ähnliche Datenfusion ohne Cloud-Abhängigkeit, ohne Lizenzkosten, mit voller Kontrolle über die Daten-Pipeline und KI-Inferenz.

---

## 2. Nutzer & Personas

### Primär: Albert (Einzelentwickler/Analyst)
- AI Engineer mit RTX 5090, Ubuntu 24.04
- Kennt CesiumJS, FastAPI, LangGraph, Docker, vLLM/Ollama
- Will: Geopolitische Lagebilder erstellen, Thesis-relevante Wargaming-Daten integrieren, OSINT-Analyse

### Sekundär: Power-User/Forscher
- Installiert über Docker Compose, bringt eigene API-Keys mit
- Will: Situational Awareness Dashboard für spezifische Regionen

---

## 3. Funktionale Anforderungen

### Must-Have (MVP)

- **[REQ-001]**: 3D Globe mit CesiumJS + Google Photorealistic 3D Tiles
  - **Akzeptanzkriterium**: Globe rendert mit 3D Tiles bei >30 FPS auf RTX 5090 unter Standardzoom
  - **Security-relevant**: nein

- **[REQ-002]**: Flugdaten-Layer (OpenSky Network + adsb.fi)
  - **Akzeptanzkriterium**: >5.000 Flugzeuge gleichzeitig darstellbar mit Dead-Reckoning bei 60 FPS
  - **Security-relevant**: nein

- **[REQ-003]**: Satelliten-Tracking (CelesTrak TLE + SGP4 via satellite.js)
  - **Akzeptanzkriterium**: Alle aktiven Satelliten (~9.000) mit korrekten Orbit-Pfaden propagiert
  - **Security-relevant**: nein

- **[REQ-004]**: Erdbeben-Layer (USGS GeoJSON Feed)
  - **Akzeptanzkriterium**: M4.5+ der letzten 7 Tage mit Magnitude-proportionalen Markern
  - **Security-relevant**: nein

- **[REQ-005]**: GLSL Post-Processing (CRT, Night Vision, FLIR)
  - **Akzeptanzkriterium**: 3 Filter umschaltbar über UI, kein Framerate-Drop >5% gegenüber Standard
  - **Security-relevant**: nein

- **[REQ-006]**: FastAPI Backend Proxy mit Caching
  - **Akzeptanzkriterium**: Alle externen API-Calls über Backend proxied, 60s Cache-TTL, <200ms API-Latenz unter 10 concurrent Requests
  - **Security-relevant**: ja (API-Key Management)

- **[REQ-007]**: RAG-System für Intelligence-Analyse
  - **Akzeptanzkriterium**: Agentic RAG mit Qdrant + Ollama/vLLM, Query-to-Response <10s für Standard-Queries auf RTX 5090
  - **Security-relevant**: nein

- **[REQ-008]**: Multi-Agent Intelligence Pipeline (LangGraph)
  - **Akzeptanzkriterium**: OSINT-Agent, Analyst-Agent und Synthesis-Agent orchestriert via LangGraph StateGraph, Streaming-Output via SSE
  - **Security-relevant**: nein

- **[REQ-009]**: Tactical C2 UI mit Operations Panel
  - **Akzeptanzkriterium**: Layer-Toggles, Shader-Selector, Hotspot-Liste, Intel-Panel, Zeitzonen-Display
  - **Security-relevant**: nein

- **[REQ-010]**: Docker Compose Deployment
  - **Akzeptanzkriterium**: `docker compose up` startet alle Services (Backend, Frontend, Qdrant, Ollama) innerhalb von 120s
  - **Security-relevant**: ja (Secret Management via .env)

### Should-Have (v1.1)

- **[REQ-011]**: Militärische ADS-B Flugverfolgung (adsb.fi Military Filter)
  - **Akzeptanzkriterium**: Militärflugzeuge farblich separiert mit ICAO-Type-Lookup
  - **Security-relevant**: nein

- **[REQ-012]**: AIS Schiffsdaten (AISStream.io WebSocket)
  - **Akzeptanzkriterium**: Live-Schiffspositionen mit Burst-Pattern (20s Connect, 60s Cache)
  - **Security-relevant**: ja (API-Key)

- **[REQ-013]**: CCTV-Overlay (öffentliche Webcams)
  - **Akzeptanzkriterium**: Kamera-Marker auf Globe mit Thumbnail-Preview bei Hover
  - **Security-relevant**: nein

- **[REQ-014]**: Straßenverkehr-Simulation (animierte Fahrzeuge auf Straßengeometrie)
  - **Akzeptanzkriterium**: Fahrzeuge bewegen sich entlang realer Straßennetze in Fokus-Städten
  - **Security-relevant**: nein

- **[REQ-015]**: Geopolitische Hotspot-Datenbank mit RAG-Kontext
  - **Akzeptanzkriterium**: 50+ Hotspots mit jeweils >10 indexierten Quell-Dokumenten in Qdrant
  - **Security-relevant**: nein

### Nice-to-Have (Backlog)

- **[REQ-020]**: WebSocket Push für Live-Updates (statt Polling)
- **[REQ-021]**: Multi-Monitor-Support (Globe auf Monitor 1, Intel auf Monitor 2)
- **[REQ-022]**: Wargaming-Integration (LangGraph Multi-Agent aus Thesis)
- **[REQ-023]**: Audio-Alerts bei Threat-Level-Änderungen
- **[REQ-024]**: Export Intelligence Reports als PDF/DOCX

---

## 4. Nicht-funktionale Anforderungen

- **Performance**: Globe-Rendering >30 FPS mit allen Layern aktiv auf RTX 5090 / 64GB RAM
- **Latenz**: Backend API <200ms p95, RAG Query <10s p95 (Qwen3-32B auf vLLM)
- **Sicherheit**: API-Keys nur in .env, nie im Frontend exponiert; alle externen Calls über Backend-Proxy
- **Skalierbarkeit**: Single-Node-Betrieb optimiert; Docker-basiert für spätere Multi-Node-Erweiterung
- **Verfügbarkeit**: Kein SLA (lokaler Betrieb), aber graceful degradation wenn externe APIs ausfallen

---

## 5. Scope-Ausschlüsse

- **Kein Multi-User-Auth**: Single-User-System, kein Login/Sessions
- **Keine Cloud-Deployment**: Kein AWS/GCP/Azure — rein lokal
- **Kein Mobile**: Desktop-First (1920x1080+)
- **Keine proprietären Daten**: Nur öffentlich zugängliche Feeds
- **Kein Echtzeit-Streaming-Video**: CCTV nur als Thumbnails, kein Video-Player
- **Kein Fine-Tuning**: Modelle werden as-is über Ollama/vLLM genutzt

---

## 6. Abhängigkeiten & Risiken

| Abhängigkeit | Risiko | Mitigation |
|---|---|---|
| Google 3D Tiles API Key | Rate-Limiting bei $200 Free-Tier Überschreitung | Budget-Alert, Fallback auf OpenStreetMap Buildings |
| OpenSky Network API | Häufige Downtime, 10s Rate-Limit | adsb.fi als Fallback, aggressive Caching |
| CelesTrak TLE Data | Gelegentlich outdated TLEs | Täglicher Cron-Refresh |
| Ollama/vLLM Inference | Modell-Qualität variiert, VRAM-Limits | Modell-Benchmark vor Integration, Fallback auf kleinere Modelle |
| CesiumJS Rendering | WebGL-Kompatibilität | Chrome/Chromium als Referenz-Browser |

---

## 7. Erfolgskriterien

1. `docker compose up` → System ist in <120s betriebsbereit
2. Globe mit 3D Tiles + 3 aktive Daten-Layer bei >30 FPS
3. RAG-basierte Intelligence-Query mit relevanten Ergebnissen in <10s
4. Alle 3 visuellen Filter (CRT/NV/FLIR) ohne Rendering-Artefakte
5. Graceful Degradation: System funktioniert wenn einzelne externe APIs ausfallen
