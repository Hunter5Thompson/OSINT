# Teil-Spec 07 — CHRONIK-Query-Vertrag

> **Parent:** [Spatial-Scope-Index](../2026-07-31-spatial-scope-drilldown-design.md)
>
> **Normativer Besitz:** Timeline-Request, Filterpräzision, Response-Accounting,
> statische Query-Compiler, Migrationsfolge und Cross-Scope-Stale-Verhalten der Hooks.
>
> **Voraussetzungen:** [02 — Scope-Identität](02-scope-identity-and-boundary-policy.md)
> und [04 — Catalog-Verträge](04-spatial-catalog-contracts.md). Exact-Graph-Felder
> gehören [08](08-neo4j-normalization.md).

---

## 14. CHRONIK- und Backend-Query-Vertrag

### 14.1 Request

Alle betroffenen Timeline-Endpunkte erhalten:

```text
scope_key=<opaque key>
catalog_revision=<exact revision>
```

`bbox` bleibt für explizite Viewport-/AOI- und Legacy-Nutzung erhalten, ist aber mit `scope_key` gegenseitig exklusiv. `scope_key + bbox` ergibt `422`.

Der Browser sendet für einen semantischen Scope niemals selbst berechnete Bounds. Das Backend löst den Key gegen exakt die angeforderte Katalogrevision auf.

`SpatialQueryRef` wird nicht erneut deklariert. Seine einzige TypeScript-Heimat ist
[§8.1](03-frontend-core-and-navigation.md#81-öffentliche-typen); der Timeline-Adapter
importiert ihn:

```ts
import type { SpatialQueryRef } from "../spatial/contracts";

interface TimeWindowQuery {
  readonly tStart: string;
  readonly tEnd: string;
  readonly domain?: "events" | "movements";
  readonly tier?: "coarse" | "fine";
  readonly movementKind?: MovementKind;
  readonly spatialScope?: SpatialQueryRef;
  readonly bbox?: readonly [number, number, number, number];
  readonly limit?: number;
}
```

Ein Runtime-Validator stellt sicher, dass `spatialScope` und `bbox` nicht zusammen serialisiert werden.

### 14.2 Response-Accounting

```py
class SpatialFilterMode(StrEnum):
    GLOBAL = "global"
    SEMANTIC_KEY = "semantic_key"
    POINT_IN_BOUNDARY = "point_in_boundary"
    BBOX_APPROXIMATE = "bbox_approximate"


class SpatialCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class SpatialApplicationV1(BaseModel):
    schema_version: Literal[1] = 1
    requested_scope_key: str | None
    catalog_revision: str | None
    derivation_revision: str | None
    boundary_policy: str | None
    relation: Literal["occurs-in", "intersects"]
    mode: SpatialFilterMode
    completeness: SpatialCompleteness
    included_count: int = Field(ge=0)
    excluded_unlocated_count: int = Field(ge=0)
    excluded_conflict_count: int = Field(ge=0)
    excluded_stale_revision_count: int = Field(ge=0)
    excluded_unsupported_count: int = Field(ge=0)
```

`WindowResponse`, `HistogramResponse` und relevante Detailantworten erhalten
`spatial_application`. Bei globalen Requests wird ebenfalls `mode=global`
zurückgegeben; das verhindert implizite Semantik aus fehlenden Feldern. Ein neuer
Client sendet auch für `world` den vollständigen Token. Bei einem Legacy-Request ganz
ohne `scope_key`/BBox bleiben die vier optionalen Identitätsfelder dagegen `null`,
damit der globale Timeline-Pfad nicht künstlich vom Spatial Catalog abhängt.

`included_count` zählt stets unterschiedliche Top-Level-Domainrecords vor
Pagination/`LIMIT`: bei Eventantworten `DISTINCT ev`, bei Movement-Antworten den im
jeweiligen Endpoint definierten Track. `samples.length` ist dagegen die tatsächlich
zurückgegebene Seitenlänge. Ein Event mit mehreren passenden Locations erhöht
`included_count` genau einmal.

`requested_scope_key` spiegelt den validierten Request-Wert wörtlich. Der intern
aufgelöste Katalog-Key bleibt kanonisch im `SpatialScopeTokenV1`; er darf das
Echo-Feld nicht umdeuten. Dadurch bleiben auch reviewte Alias- oder
Normalisierungsübergänge vergleichbar, ohne den Feldnamen semantisch zu überladen.

Definitionen:

- `semantic_key`: Datensatz besitzt einen kanonischen materialisierten Scope-Key der angeforderten Relation.
- `point_in_boundary`: echte Punktkoordinate wurde gegen die kanonische Boundary geprüft.
- `bbox_approximate`: nur die Boundary-Extent wurde angewendet; Treffer können außerhalb des Polygons liegen.
- `partial`: ein Teil der potenziell relevanten Daten war mangels Geo-Metadaten oder wegen widersprüchlicher Codes nicht entscheidbar und wurde ausgeschlossen.

Records aus einer für den angeforderten Scope nicht freigegebenen
Derivationsrevision werden ebenfalls ausgeschlossen und separat über
`excluded_stale_revision_count` gezählt.

`excluded_unsupported_count` zählt Records mit angefragtem materialisiertem
Scope-Key, deren Normalisierungszustand weder valide, Conflict noch Stale ist. Das
Feld ist Teil des V1-Wire-Vertrags und darf nicht nur intern berechnet und danach
verworfen werden.

„Partial“ bedeutet niemals „global ergänzt“. Ein Exact-Read darf unlocated Records
nicht aus einem globalen Fenster einem einzelnen Scope zurechnen. Die
scope-spezifische Aktivierung setzt deshalb vollständige Coverage-Evidenz voraus;
ohne diese Evidenz bleibt der Scope `bbox_approximate + partial`. Ein aktivierter
Exact-Scope meldet `excluded_unlocated_count=0`, während Conflict, Stale und
Unsupported weiterhin pro Request gemessen werden.

### 14.3 Interne Auflösung

```py
@dataclass(frozen=True, slots=True)
class ResolvedSpatialConstraint:
    token: SpatialScopeTokenV1
    extent: GeoExtent
    country_scope_key: str | None
    admin1_scope_key: str | None
    admin2_scope_key: str | None
```

Diese Klasse ist intern. Sie enthält keine Cypher-Fragmente und keine Property-Namen aus Manifestdaten.

### 14.4 Statische Query-Compiler

Für Event-Queries existieren allowlisted, statische Varianten:

```py
_EVENT_QUERY_BY_SCOPE_KIND: Final[dict[ScopeKind, str]] = {
    ScopeKind.WORLD: _EVENTS_GLOBAL_QUERY,
    ScopeKind.COUNTRY: _EVENTS_COUNTRY_SCOPE_QUERY,
    ScopeKind.ADMIN1: _EVENTS_ADMIN1_SCOPE_QUERY,
    ScopeKind.ADMIN2: _EVENTS_ADMIN2_SCOPE_QUERY,
}
```

Beispiel Country-Predicate im vollständigen statischen Template:

```cypher
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.country_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
WITH ev, l
ORDER BY CASE WHEN l.lat IS NOT NULL AND l.lon IS NOT NULL THEN 0 ELSE 1 END ASC,
         coalesce(l.id, l.location_id, l.name, elementId(l)) ASC
WITH ev, collect(l)[0] AS l
ORDER BY ev.timeline_at ASC,
         coalesce(ev.id, ev.event_id, toString(elementId(ev))) ASC
LIMIT $limit
RETURN ...
```

Admin-Templates verwenden ausschließlich `l.admin1_scope_key` beziehungsweise `l.admin2_scope_key`. Scope-Kind wählt ein konstantes Template; `scope_key`, Zeit, Limit und alle weiteren Werte bleiben Parameter. Das Katalogmanifest kann weder Query-Text noch Property-Namen liefern.

Das verpflichtende `MATCH` ist Absicht: Exact-Scope-Queries beginnen bei der
indexierten `Location(scope_key, spatial_derivation_revision)` und traversieren von
dort zu Events. Die erste Sortierung wählt eine reproduzierbare Repräsentativ-
Location; `collect(l)[0]` kollabiert anschließend alle passenden Locations vor dem
Event-`LIMIT` auf genau eine Eventzeile und bevorzugt dabei eine koordinatentragende
Location. Die Count-Variante misst zuerst unabhängig alle `DISTINCT ev` mit dem
angefragten Scope-Key und reconciliert diese Referenzmenge anschließend gegen die
disjunkten Kategorien Included, Conflict, Stale und Unsupported. Ein globaler
Unlocated-Full-Window-Scan ist kein Exact-Accounting.

Der Histogramm-Pfad verwendet getrennte statische Templates: ein schmales
Bucket-Template mit `time`, `codebook_type`, `severity`, begrenzte Event- und
Incident-Notable-Templates sowie ein schmales Geo-Template. Alle Reads samt
Accounting laufen in derselben read-only Neo4j-Transaktion, damit Löschungen zwischen
Sample und Count keinen falschen Storage-Fehler erzeugen.

`$compatible_revisions` stammt aus der reviewten
[Katalogmatrix (§7.5)](02-scope-identity-and-boundary-policy.md#75-katalogrevision-versus-daten-derivationsrevision),
nicht aus Client-Input. Separate statische Accounting-Queries zählen Records mit passendem
Scope-Key, aber inkompatibler/null Derivationsrevision als stale.

### 14.5 Migrationsfolge der Filterpräzision

1. **Visual/approximate:** Backend löst Country-Boundary auf und nutzt die vorhandene antimeridianfähige BBox-Query. Antwort ist zwingend `bbox_approximate + partial`.
2. **Forward writes:** Location-Writer setzen materialisierte Scope-Keys und `geo`.
3. **Backfill:** idempotent, dry-run-first, mit Coverage-/Conflict-Report.
4. **Exact activation:** statische semantische Templates werden nur für Kinds aktiviert, deren Daten-Gate bestanden ist.
5. **Kein Auto-Fallback:** Wenn exact für einen aktiv gemeldeten Kind ausfällt, folgt `503/SPATIAL_FILTER_UNAVAILABLE`, nicht BBox oder global.

Movement-Tracks bleiben zunächst `bbox_approximate`. Eine Country-BBox ist keine Polygon-Intersection. Exakte Track-Scope-Semantik erfordert materialisierte Sample-Scope-Keys oder einen separaten serverseitigen Geometry-Intersection-Pfad.

### 14.6 Hook-Verhalten bei Scope-Wechsel

`useTimeWindow` und `useTimeHistogram` unterscheiden Refresh derselben Scope-ID von einem Scope-Commit:

- gleicher `scopeKey + catalogRevision`: Stale-while-refresh erlaubt;
- anderer Scope-Token: alte Daten synchron auf `null`, Request aborten, Loading/Skeleton anzeigen;
- verspätetes Resultat: Sequence Guard plus Scope-Token-Vergleich verwirft es;
- Fehler: explizites `error`, nicht leerer Catch; alte Daten eines anderen Scope bleiben verborgen.

Damit erscheinen nie Ukraine-Daten unter einem neuen Polen-Breadcrumb.

Das „synchron“ wird nicht mit einem `setData(null)` erst im Effect behauptet. Der Hook
speichert ein Envelope und gated den Return bereits im Render:

```ts
interface ScopedDataEnvelope<T> {
  readonly scopeTokenKey: string;
  readonly requestKey: string;
  readonly data: T;
}

const activeScopeTokenKey = spatialScope
  ? `${spatialScope.scopeKey}@${spatialScope.catalogRevision}`
  : "hydrating";

const visibleData = envelope?.scopeTokenKey === activeScopeTokenKey
  ? envelope.data
  : null;
```

Der Effect abortet/holt danach. Innerhalb desselben `scopeTokenKey` darf das Envelope
bei Refresh oder Time-Range-Änderung vorübergehend sichtbar bleiben; die UI besitzt
dafür ihren bestehenden Loading-Indikator. Vor dem Speichern prüft der Hook zusätzlich,
dass bei vorhandenem `spatialScope`
`response.spatial_application.requested_scope_key` und `catalog_revision` zum Request
passen. Ein semantisch falsch etikettiertes Backend-Resultat wird als Contract-Fehler
verworfen.

Der V1-Decoder verlangt alle normativen Felder und bekannten Enum-Werte, toleriert
aber additive unbekannte Felder derselben `schema_version`. So bleiben getrennte
Frontend-/Backend-Rollouts vorwärtskompatibel; unbekannte Enum- oder Schemawerte
bleiben weiterhin harte Contract-Fehler.

---
