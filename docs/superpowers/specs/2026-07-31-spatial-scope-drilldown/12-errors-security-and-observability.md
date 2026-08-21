# Teil-Spec 12 — Fehler, Security und Observability

> **Parent:** [Spatial-Scope-Index](../2026-07-31-spatial-scope-drilldown-design.md)
>
> **Normativer Besitz:** Fehlerklassen, Retry-Policy, Fail-closed-Regeln,
> Ressourcenmissbrauchsschutz sowie strukturierte Logs und Metriken.
>
> **Voraussetzungen:** [01 — globale Invarianten](01-architecture-and-invariants.md)
> und [02 — Scope-Identität](02-scope-identity-and-boundary-policy.md). Fachliche
> Teile dürfen strengere, aber keine schwächeren Regeln setzen.

---

## 20. Fehlersemantik

### 20.1 Klassen

| Klasse | Beispiele | Scope-Commit? | UI |
|---|---|---:|---|
| Input | ungültiger/zu langer Key | nein | Error, URL reparieren falls Hydration |
| Catalog metadata | Attribution fehlt/ungültig/zu groß | nein | `CATALOG_UNAVAILABLE`/503; andere Routen bleiben gesund |
| Semantic resolution | unbekannt, kaputte Lineage, Revision fehlt | nein | alter Scope bleibt |
| Navigation | Router-Echo bleibt zwei Sekunden aus | nein | `URL_SYNC_FAILED`, alter Scope + expliziter Retry |
| Presentation | Asset fehlt/zu groß, Cesium-Fehler | ja | semantic-only + Warning |
| Resource saturation | Asset-Read-Semaphore voll | ja | `ASSET_BUSY`, `Retry-After` anzeigen/berücksichtigen |
| Query consumer | Neo4j/Qdrant nicht verfügbar | ja | Consumer-Fehler im aktiven Scope |
| Capability | Layer/Tool unterstützt Scope nicht | ja | unsupported/partial, kein globaler Fallback |
| Superseded | schneller neuer Intent | nein zusätzlicher Commit | still verwerfen |

### 20.2 Retry

- Resolve 404: kein automatischer Sofort-Retry; 30-s-Negative-Cache.
- Resolve/Asset 5xx oder Network: ein jittered Retry nur bei weiterhin aktueller Generation und sichtbarem User-Intent; Prefetch retryt nicht.
- Asset 429: höchstens ein Retry nach serverseitigem `Retry-After`, nur für dieselbe
  aktive Presentation-Generation; kein Retry-Sturm und kein Prefetch-Retry.
- `URL_SYNC_FAILED`: kein automatischer Loop. Die UI zeigt „Navigation konnte nicht
  synchronisiert werden“ und bietet denselben Command explizit erneut an; bis dahin
  bleiben Store und URL auf dem letzten committed Scope.
- Query-Consumer folgt bestehender Retry-Policy, aber bindet Retry an denselben Scope-Token.
- Revision 409: Der Adapter transportiert die aktive Revision strukturiert im
  `ScopeProblem`; die UI bietet genau eine sichtbare Rehydrate-Aktion. Erst dieser
  Command validiert und pinnt die aktive Revision neu. Kein Parsing von Meldungstext,
  kein stilles Umschreiben und kein automatischer 409-Retry.

### 20.3 Fail-closed-Regel

Wenn ein Consumer einen angeforderten nicht-globalen Scope nicht anwenden kann, gibt er einen strukturierten Fehler oder `unsupported/partial` zurück. Er liefert niemals globale Daten unter dem scoped Breadcrumb.

---

## 21. Security, Robustheit und Ressourcenmissbrauch

Threats und Controls:

| Threat | Control |
|---|---|
| Path Traversal über Scope/Asset | harte Grammatik, Manifest-Lookup, keine Pfadkonkatenation |
| beliebige Remote-Geometrie | same-origin Asset-ID, keine URL im Caller-Vertrag |
| JSON-/Geometry-Bombe | Content-Length, Byte-, Feature-, Ring-, Vertex-, Depth-Limits vor Cesium |
| Asset-Request-Flood | globale Backend-Semaphore, kurzer Acquire-Timeout, `429` + `Retry-After`; kein File-Open bei Ablehnung |
| XSS über Labels/Attribution | als Text rendern, kein `dangerouslySetInnerHTML` |
| stale Race | Foreground-Generation vor/nach jedem Await; Consumer-Revisionen |
| Cache-Abort zerstört aktiven Load | ref-counted In-flight-Consumer |
| Query Injection | statische Template-Auswahl, ausschließlich Parameterwerte |
| LLM entfernt Scope | `ToolRuntime`-Injection, kein modellkontrollierter Scope-Parameter |
| geopolitische Injection | reviewte Boundary-Policy und Provenance; keine Source-Regel im Prompt |
| GPU-/Event-listener-Leak | ein Owner, deterministisches remove/destroy, Listener-Cleanup, Zyklentest |
| manipulierte Parent-Kette | serverseitig rekonstruierte Lineage |
| Revisions-Mix | Token, Manifest, Scope-Bundle und Response tragen Catalog-Revision; content-addressed Assets werden ausschließlich über das Manifest derselben Revision aufgelöst; alte Revision 409 statt Fallback |

Telemetry enthält Scope-Key, Katalogrevision, Mode, Dauer und Zählwerte, aber keinen freien Query-Text und keine ungefilterten Dokumentinhalte.

Der Spatial Scope ist ein analytischer Filter, keine Mandanten- oder
Autorisierungsgrenze. Falls ODIN später regionenbasierte Zugriffsrechte erhält, werden
sie serverseitig als separater Authorization-Constraint mit Schnittmenge zum
angeforderten Scope durchgesetzt; das UI-Token allein kann niemals Zugriff gewähren.

Die aktuelle Deployment-Posture ist ausdrücklich ein vertrauenswürdiges On-Prem-/LAN-
Netz: Spatial-Read-Endpunkte besitzen in V1 keine eigene Benutzer-Authentisierung und
kein per-IP-Rate-Limit. Die globale Asset-Concurrency begrenzt Ressourcenverbrauch,
ersetzt aber kein Edge-Rate-Limit. Vor Exposition außerhalb dieses Netzes sind
Reverse-Proxy-Authentisierung und Rate-Limiting ein verpflichtendes Deployment-Gate.

---

## 22. Observability

Strukturierte Events:

```text
spatial_scope_transition_started
spatial_scope_transition_committed
spatial_scope_transition_failed
spatial_scope_transition_superseded
spatial_catalog_resolve
spatial_asset_load
spatial_asset_rejected_busy
spatial_presentation_ready
spatial_presentation_failed
spatial_filter_applied
spatial_filter_unsupported
spatial_prefetch
```

Gemeinsame Felder:

```text
scope_key
catalog_revision
derivation_revision
state_revision (frontend only)
cause
consumer
filter_mode
completeness
duration_ms
cache_status
included_count
excluded_unlocated_count
excluded_conflict_count
excluded_stale_revision_count
excluded_boundary_uncertain_count
```

Metriken/Debug-Gates:

- Resolve-/Asset-Latenz p50/p95;
- Cache hit/miss/eviction;
- superseded transition count;
- Primitive-/Listener-Count pro aktivem Viewer;
- Query count und Latenz nach Filtermodus;
- räumliche Coverage pro Source-Lane und Katalogrevision;
- Stale-Anteil pro Lane/Derivationsrevision: jeder Wert über null sichtbar, über 1 %
  Alert und Blockade der Exact-Promotion;
- Anzahl `semantic-only` und `unsupported`.

`state_revision` ist eine lokale monotone UI-Revision und darf nicht mit `catalog_revision` verwechselt werden.

---
