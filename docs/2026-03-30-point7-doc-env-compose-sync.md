# Point 7 Umsetzung: Doku + Env + Compose Sync

Datum: 2026-03-30

## Ziel

Konsistenz zwischen:
- `README.md`
- `.env.example`
- `docker-compose.yml`

für den aktuellen Laufzeitstand mit `vLLM + TEI + Neo4j` (statt Ollama).

## Durchgeführte Änderungen

## 1) README aktualisiert

Datei: `README.md`

- Referenzen auf `Ollama` entfernt/ersetzt durch `vLLM + TEI`.
- Architektur-Block auf aktuellen Stack angepasst.
- Klarstellung ergänzt:
  - Backend läuft im Container intern auf `8000`.
  - Backend ist auf dem Host via `8080:8000` erreichbar.
- Infrastruktur-Quickstart aktualisiert:
  - `redis`, `qdrant`, `neo4j`, `vllm`, `tei-embed`, `tei-rerank`
- Host-Port-Übersicht für Compose ergänzt.
- Tech-Stack-Abschnitt auf aktuelle Modelle/Embedding-Dimensionen angepasst.

## 2) .env.example konsolidiert

Datei: `.env.example`

- `NEO4J_USER` und `NEO4J_URL` ergänzt.
- Inference/Embedding-Block aktualisiert auf vLLM/TEI:
  - `VLLM_URL=http://localhost:8000`
  - `TEI_EMBED_URL=http://localhost:8001`
  - `TEI_RERANK_URL=http://localhost:8002`
  - `VLLM_MODEL=models/qwen3.5-27b-awq`
  - `EMBEDDING_DIMENSIONS=1024`
- Veralteten/falschen Eintrag entfernt:
  - `VLLM_URL=http://localhost:8001`
- Kommentar ergänzt, dass Compose interne Service-URLs überschreibt.

## 3) Compose bereinigt

Datei: `docker-compose.yml`

- Irreführende Frontend-Runtime-Variable entfernt:
  - `VITE_API_URL=http://localhost:8080`

Hinweis: Die Frontend-App wird als statisches Build über Nginx ausgeliefert; diese Runtime-Variable war in dieser Form nicht wirksam.

## Ergebnis

Die zentrale Dokumentation, die Beispiel-Umgebungsvariablen und die Compose-Definition sind jetzt auf denselben Infrastrukturstand ausgerichtet (vLLM/TEI/Neo4j statt Ollama).

## Verifikation (manuell empfohlen)

1. `cp .env.example .env`
2. `docker compose config` (Syntax/Interpolation prüfen)
3. `docker compose up -d`
4. Erreichbarkeit prüfen:
   - Frontend: `http://localhost:5173`
   - Backend Health: `http://localhost:8080/api/v1/health`
   - vLLM Health: `http://localhost:8000/health`
   - Neo4j Browser: `http://localhost:7474`
