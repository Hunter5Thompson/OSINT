Tests sind durch.

  Teststatus

  - services/data-ingestion: 407 passed, 1 skipped, 1 deselected
  - services/backend: 122 passed
  - services/intelligence: 157 passed
  - services/vision-enrichment: 9 passed
  - services/frontend npm run type-check: passed
  - services/frontend npm run build: passed
  - services/frontend npm run lint: passed mit 6 warnings, alle in src/components/graph/GraphCanvas.tsx wegen ungenutzter eslint-disable Kommentare

  GDELT Raw ist nicht mehr trocken:

  - letzter Slice: 20260425200000
  - Neo4j: 42 GDELTEvent, 326 GDELTDocument
  - Qdrant: 326 Punkte mit source=gdelt_gkg
  - pending Neo4j/Qdrant: 0

  Container-Überblick
  Aktiv laufen aktuell 11 Container. Davon gehören 9 direkt zur OSINT-App im Docker-Netz osint_default:

  | Container | Rolle | Extern |
  |---|---|---|
  | odin-data-ingestion-spark | Scheduler/Ingestion/GDELT Raw | nein |
  | osint-backend-1 | FastAPI Backend | 8080 |
  | osint-intelligence-1 | LangGraph/RAG/Extraction | 8003 |
  | osint-vllm-9b-1 | lokales vLLM 9B | 8000 |
  | osint-tei-embed-1 | Embeddings | 8001 |
  | osint-tei-rerank-1 | Reranking | 8002 |
  | osint-qdrant-1 | Vector DB | 6333/6334 |
  | osint-neo4j-1 | Graph DB | 7474/7687 |
  | osint-redis-1 | Streams/Cache/State | 6379 |

  Zusätzlich laufen außerhalb des OSINT-Compose-Projekts:

  - crawl4ai-crawl4ai-1 auf 11235
  - docling-docling-serve-1 auf 5001

  Frontend ist gerade kein laufender Docker-Container. osint-frontend-1 ist nur Created; Port 5173 kommt von einem lokalen Vite-Prozess.

  Verdrahtung

  Browser
    -> Vite Frontend :5173
    -> Backend :8080

  Backend
    -> Intelligence http://intelligence:80
    -> Qdrant http://qdrant:6333
    -> Neo4j bolt://neo4j:7687
    -> Redis redis://redis:6379
    -> TEI Embed http://tei-embed:80
    -> TEI Rerank http://tei-rerank:80
    -> vLLM http://vllm:8000

  Intelligence
    -> vLLM http://vllm:8000
    -> Qdrant http://qdrant:6333
    -> Neo4j bolt://neo4j:7687
    -> TEI Embed http://tei-embed:80
    -> TEI Rerank http://tei-rerank:80

  Data Ingestion Spark
    -> external Spark vLLM http://192.168.178.39:8000
    -> Qdrant http://qdrant:6333
    -> Neo4j bolt://neo4j:7687
    -> Redis redis://redis:6379
    -> TEI Embed http://tei-embed:80
    -> external feeds/GDELT CDN
    -> /data/gdelt Parquet volume

  Wichtig: Der alte Legacy-DOC-GDELT-Collector läuft noch parallel und produziert weiter Fehler/total_new: 0. Der neue Raw-Pfad funktioniert aber bereits und schreibt echte Daten. Der
  nächste saubere Schritt ist, den Legacy-GDELT-Scheduler-Pfad zu deaktivieren und die Doku/Commands auf source=gdelt_gkg statt gdelt_raw zu korrigieren.