# P0a - Backend Runtime Reliability (Design Spec)

**Datum:** 2026-05-31
**Status:** Implemented on 2026-05-31

**Implementation:** `5da7524` (`fix(backend): harden incident rehydrate and redis shutdown`)
**Ziel:** Den produktionsrelevanten Incident-Rehydrate-Crash sofort beheben und
die betroffenen Async-Lifecycle-Grenzen ohne breites Refactoring haerten.

## 1. Motivation

Der Incident-Auto-Promoter rehydriert beim Start seine eigenen offenen oder
promoteten Incidents. Der aktuelle Pfad ruft in
`app/services/incident_store.py::list_owned_for_rehydrate()` jedoch
`read_query(cypher)` ohne das verpflichtende `params`-Argument auf.

`app/services/neo4j_client.py::read_query()` verlangt:

```python
async def read_query(cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
```

Gegen echtes Neo4j entsteht deshalb beim Startup ein `TypeError`. Die bestehende
Unit-Test-Suite sieht den Fehler nicht, weil ein uneingeschraenktes `AsyncMock`
beliebige Aufrufsignaturen akzeptiert.

Daneben verwenden drei Redis-Close-Pfade die veraltete Coroutine `close()`
statt `aclose()`. Das ist kein gleich schwerer Fehler, aber ein kleiner,
risikoarmer Lifecycle-Fix im selben Backend-Reliability-Slice.

## 2. Engineering Lens

| Frage | Antwort |
|---|---|
| Welcher fachliche Invariant wird geschuetzt? | Ein Backend-Neustart darf vorhandene Auto-Promoter-Incidents rehydrieren, ohne am Datenbankvertrag zu scheitern. Ressourcen muessen beim Shutdown ueber die unterstuetzte Async-API geschlossen werden. |
| Welcher Context besitzt ihn? | Der Incident-Context besitzt Rehydrate. Der Backend-Lifecycle besitzt Redis-Close. |
| Was ist der kleinste explizite Vertrag? | Jeder Neo4j-Read erhaelt ein Parameter-Dict. Angefasste DB-Boundary-Tests pruefen Signatur und Argumente. Redis-Clients werden nur ueber die deklarativ unterstuetzte Async-API geschlossen. |
| Welcher Test ist vor der Aenderung rot? | Der Rehydrate-Test mit `autospec=True` scheitert am fehlenden `params`-Argument. Drei gezielte Redis-Tests erwarten `aclose()` und scheitern gegen den Ist-Stand. |
| Was verschwindet? | Eine duplizierte Inline-Cypher-Query, ein durch Mocks maskierter Signaturfehler und drei veraltete Redis-Aufrufe. |

Leitlinie: Dijkstra fuer die Groesse des Fixes, Parnas fuer die Query-Grenze,
Beck und Feathers fuer den abgesicherten Verhaltenswechsel. DDD liefert hier
den Context-Namen, aber keine zusaetzliche Schicht.

## 3. Scope

### 3.1 Incident-Rehydrate test-first reparieren

Die bestehende Inline-Query ist nicht semantisch identisch mit
`INCIDENT_LIST_OPEN`: Rehydrate sortiert nach dem zuletzt geschriebenen
`i.ordinal`, waehrend die allgemeine Liste nach `i.trigger_ts` sortiert. Bei
mehr als 500 Kandidaten koennte ein Austausch die rehydrierte Teilmenge
veraendern.

`app/cypher/incident_read.py` erhaelt deshalb ein eigenes Template
`INCIDENT_LIST_REHYDRATE_CANDIDATES`. Es bindet den Limit-Parameter, behaelt
aber die existierende Sortierung:

```python
INCIDENT_LIST_REHYDRATE_CANDIDATES = (
    "MATCH (i:Incident) "
    "WHERE i.status IN ['open', 'promoted'] "
    "RETURN i.id AS id, i.kind AS kind, i.title AS title, "
    "       i.severity AS severity, i.lat AS lat, i.lon AS lon, "
    "       i.location AS location, i.status AS status, "
    "       toString(i.trigger_ts) AS trigger_ts, "
    "       toString(i.closed_ts) AS closed_ts, "
    "       i.sources AS sources, i.layer_hints AS layer_hints, "
    "       i.timeline_json AS timeline_json "
    "ORDER BY i.ordinal DESC "
    "LIMIT $limit"
)
```

`app/services/incident_store.py` verwendet eine benannte Obergrenze:

```python
_REHYDRATE_LIMIT = 500

rows = await read_query(
    INCIDENT_LIST_REHYDRATE_CANDIDATES,
    {"limit": _REHYDRATE_LIMIT},
)
```

Das entfernt die Inline-Duplikation, erfuellt den Neo4j-Read-Vertrag explizit
und behaelt die bestehende Kandidatenmenge bei. Das anschliessende
Python-Filtering auf `auto_promoter:v1` bleibt unveraendert.

Vor der Implementierung wird der bestehende Test
`test_list_owned_for_rehydrate_filters_by_auto_promoter_marker` in
`tests/test_incident_store.py` direkt gehaertet:

```python
with patch.object(
    incident_store,
    "read_query",
    autospec=True,
    return_value=[row1, row2, row3],
) as mock_read:
    result = await incident_store.list_owned_for_rehydrate()

mock_read.assert_awaited_once_with(
    INCIDENT_LIST_REHYDRATE_CANDIDATES,
    {"limit": _REHYDRATE_LIMIT},
)
```

Der gehaertete Test ist gegen den Ist-Stand rot: Der autospezifizierte Mock
weist das fehlende Argument zurueck. Erst danach folgt der Einzeiler im
Produktionscode.

### 3.2 DB-Boundary-Mock-Regel

Fuer neu angefasste Tests an `read_query()` und `write_query()` gilt:

- `autospec=True` oder ein gleichwertig strikter Spec-Mock.
- Bei relevanten Queries `assert_awaited_once_with(template, params)`.
- Keine breit angelegte Mock-Migration im selben Hotfix.

Damit wird die Ursache adressiert: Signatur-Drift darf an der DB-Grenze nicht
mehr still durch Tests laufen.

### 3.3 Redis Async-Close aktualisieren

Interne Redis-Clients wechseln von `await client.close()` auf
`await client.aclose()`:

- `app/services/cache_service.py`
- `app/services/signal_stream.py` an beiden Close-Pfaden

Der oeffentliche Lifecycle-Vertrag `CacheService.close()` bleibt erhalten.
Es wird keine API umbenannt.

`Redis.aclose()` ist ab `redis-py 5.0.1` vorhanden; `close()` ist dort nur noch
der deprecated Kompatibilitaetsalias. Das Backend deklariert aktuell
`redis[hiredis]>=5.0`, obwohl das lokale Lockfile bereits `redis 7.4.0`
aufloest. Der Dependency-Vertrag wird deshalb praezisiert:

```toml
"redis[hiredis]>=5.0.1",
```

Das gitignorierte Lockfile wird danach lokal regeneriert. Ein Versionssprung
ist im aktuellen Worktree nicht erforderlich; die Untergrenze dokumentiert die
tatsaechlich verwendete API.

### 3.4 Redis-Close test-first absichern

Die bestehenden Tests ueben die drei internen Redis-Close-Pfade nicht
explizit aus. Vor dem Produktionscode werden deshalb gezielte Tests ergaenzt:

- `tests/unit/test_cache_service.py::test_close_awaits_redis_aclose`
- `tests/unit/test_signals_stream.py::test_redis_consumer_closes_client_on_stop`
- `tests/unit/test_signals_stream.py::test_redis_consumer_closes_failed_client_before_retry`

Die Tests verwenden einen Async-Mock-Client und pruefen
`client.aclose.assert_awaited_once_with()`. Gegen den Ist-Stand sind sie rot,
weil dieser `client.close()` aufruft. Damit haengt der TDD-Nachweis nicht von
einer zufaellig emittierten `DeprecationWarning` ab.

## 4. Explizit Out of Scope

- Repo-weites Ruff- oder Mypy-Aufraeumen.
- SSE-Deduplikation, Qdrant-Client-Deduplikation oder Vessel-Refactoring.
- Config-Zentralisierung.
- Entfernen der ueberfaelligen `/api/v1`-Aliase.
- Ein generisches Repository-Pattern oder Dependency-Injection-Framework.

Diese Themen bleiben getrennte PRs. Der Crash-Fix darf nicht auf strukturelle
Aufraeumarbeiten warten.

## 5. Verification

Aus `services/backend`:

```bash
uv run pytest tests/test_incident_store.py -q
uv run pytest tests/unit/test_cache_service.py -q
uv run pytest tests/unit/test_signals_stream.py -W error::DeprecationWarning -q
uv run pytest -q
uv run ruff check app/services/incident_store.py app/services/cache_service.py app/services/signal_stream.py
uv run python -c 'import redis; from redis.asyncio import Redis; print(redis.__version__); assert hasattr(Redis, "aclose")'
```

Zusaetzlich wird `rg -n "\.close\(\)" app/services` geprueft. Verbleibende
Treffer muessen entweder nicht Redis betreffen oder begruendet sein.

Zum Implementierungszeitpunkt war die bestehende globale Mypy-Schuld kein Gate
dieses Hotfixes; fuer angefasste Dateien durften keine neuen Fehler entstehen.
Der aktuelle Repository-Qualitaetsvertrag aus `AGENTS.md` gilt unabhaengig von
diesem historischen Delivery-Slice.

## 6. Implementation Record

Der Slice wurde atomar in `5da7524` geliefert. Der Commit fuehrte das dedizierte
Rehydrate-Template samt Parameterbindung ein, stellte die drei Redis-Pfade auf
`aclose()` um und ergaenzte die beschriebenen Boundary-Tests. Spaetere
Backend-Aenderungen bauen auf diesem Vertrag auf; diese Spec ist deshalb ein
Design- und Entscheidungsrecord, kein offener Arbeitsplan.
