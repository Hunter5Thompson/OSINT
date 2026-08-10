# Teil-Spec 04 — Spatial-Catalog-Verträge

> **Parent:** [Spatial-Scope-Index](../2026-07-31-spatial-scope-drilldown-design.md)
>
> **Normativer Besitz:** Runtime-Ownership, HTTP- und Wire-Format, Backend-Modelle,
> Frontend-Decoding, Cache, Resolve-Form, Containment-Port und Backend-Lifecycle.
>
> **Voraussetzungen:** [01 — Architektur](01-architecture-and-invariants.md) und
> [02 — Scope-Identität](02-scope-identity-and-boundary-policy.md). Der Offline-Build
> ist getrennt in [05](05-boundary-build-and-antimeridian.md) verankert.

---

## 10. Spatial Catalog: Besitz, API und Wire-Format

### 10.1 Ownership

Das Backend besitzt den zur Laufzeit autoritativen Katalog. Die Build-Pipeline lebt im Data-Ingestion-Service, schreibt aber ausschließlich deterministische Artefakte nach:

```text
services/backend/data/spatial/
  source-lock.json
  catalogs/
    spatial-v1-<manifest-hash>/
      manifest.json
      attribution.json
      assets/
        <sha256>.json
```

Docker kopiert `data/`; Compose mountet `services/backend/data:/app/data`.
Intelligence erhält statt Boundary-Geometrie den Backend-validierten Scope-Token und
filtert dieselben materialisierten Scope-Keys.

### 10.2 Keine Runtime-Abhängigkeit von Drittquellen

Das Backend liefert ausschließlich lokale, versionierte Artefakte. Es gibt keinen Fallback auf externe GeoJSON-URLs. Ein fehlender Katalog ist ein lokaler Deployment-/Datenfehler und wird als `503` sichtbar.

### 10.3 HTTP-Vertrag

```text
GET /api/spatial/catalog
GET /api/spatial/scope?scope_key=<encoded>&catalog_revision=<optional>
GET /api/spatial/assets/{asset_id}
```

Als Query-Parameter erreicht auch ein encoded Slash/Backslash in `scope_key` die
Validierung und wird `422`, statt den Routerpfad zu ändern. `asset_id` ist 64-stelliges
lowercase SHA-256-Hex, wird im Manifest nachgeschlagen und nie an Pfade concateniert.

Statuscodes:

| Status | Bedeutung |
|---:|---|
| `200` | Katalog, Scope oder Asset verfügbar |
| `304` | ETag unverändert |
| `404` | syntaktisch gültiger, unbekannter Scope oder Asset |
| `409` | angeforderte Katalogrevision wird nicht mehr bedient |
| `422` | ungültiger Key oder Revision |
| `429` | globale Asset-Read-Concurrency ist ausgeschöpft; `Retry-After` ist gesetzt |
| `503` | Katalog fehlt, Hash/Schema ungültig oder kann nicht sicher geladen werden |

Aktive und unmittelbar vorherige Katalogrevision werden während Rolling Deployments parallel bedient. Eine ältere nicht verfügbare Revision wird nie still auf die aktive Revision umgebogen.

Neue Spatial-Endpunkte verwenden für erwartbare Fehler einen stabilen Body statt
unstrukturiertem Exception-Text:

```json
{
  "detail": {
    "schema_version": 1,
    "code": "CATALOG_REVISION_UNAVAILABLE",
    "message": "Requested spatial catalog revision is not served",
    "target": "spatial-v1-001122334455",
    "recoverable": true,
    "active_catalog_revision": "spatial-v1-a1b2c3d4e5f6"
  }
}
```

`code` ist geschlossen; `message` wird nie geparst. Pfade, Source-URLs und
Stacktraces bleiben intern; der Frontend-Adapter mappt Code/Status auf `ScopeProblem`.

### 10.4 Catalog Bootstrap

```json
{
  "schema_version": 1,
  "active_catalog_revision": "spatial-v1-a1b2c3d4e5f6",
  "served_catalog_revisions": [
    "spatial-v1-a1b2c3d4e5f6",
    "spatial-v1-998877665544"
  ],
  "boundary_policy": "odin-reference-v1",
  "root_scope_key": "world",
  "capabilities": {
    "max_enabled_kind": "admin1",
    "timeline_scope": "bbox_approximate",
    "intelligence_scope": "unavailable"
  },
  "attributions": [{
    "catalog_revision": "spatial-v1-a1b2c3d4e5f6",
    "representation_note": "ODIN reference boundary representation",
    "sources": [{
      "source_id": "natural-earth-admin0",
      "release": "<pinned release>",
      "license_id": "public-domain",
      "text": "Natural Earth"
    }]
  }]
}
```

`attributions` enthält je bedienter Revision genau eine validierte Projektion ihrer
`attribution.json` (1–2 Einträge, 1–32 Sources). Grenzen: Note 1–500,
`source_id`/`license_id` 1–96, Release 1–128, Text 1–300 Zeichen. HTML sowie fehlende,
doppelte, zusätzliche oder übergroße Werte sind ungültig.

Jede Source besitzt ein `release`. Die nach `source_id` sortierte Liste wird über
`attribution_sources_sha256` revisionsbildend ans Manifest gebunden; auch reine
Attribution-/Tool-Releases erzeugen eine Revision. Die aktive Revision muss
Source-Menge, Release, Lizenz und Text des aktuellen `source-lock.json` treffen. Die vorherige Revision
validiert nur ihr Manifest/Attribution und leiht nichts aus dem aktuellen Lock.

### 10.5 Scope-Bundle

```json
{
  "schema_version": 1,
  "catalog_revision": "spatial-v1-a1b2c3d4e5f6",
  "boundary_policy": "odin-reference-v1",
  "canonicalized_from": null,
  "scope": {
    "key": "country:UKR",
    "kind": "country",
    "label": "Ukraine",
    "short_label": "Ukraine",
    "parent_key": "world",
    "children_available": true,
    "presentation": "boundary"
  },
  "path": [
    {
      "key": "world",
      "kind": "world",
      "label": "World",
      "short_label": "World",
      "parent_key": null,
      "children_available": true,
      "presentation": "boundary"
    },
    {
      "key": "country:UKR",
      "kind": "country",
      "label": "Ukraine",
      "short_label": "Ukraine",
      "parent_key": "world",
      "children_available": true,
      "presentation": "boundary"
    }
  ],
  "presentation": {
    "preferred_lod": "regional",
    "outline_lods": {
      "overview": {
        "asset_id": "<sha256>",
        "media_type": "application/vnd.odin.boundary+json;v=1",
        "byte_length": 4567,
        "vertex_count": 320,
        "role": "render",
        "lod": "overview"
      },
      "regional": {
        "asset_id": "<sha256>",
        "media_type": "application/vnd.odin.boundary+json;v=1",
        "byte_length": 12345,
        "vertex_count": 987,
        "role": "render",
        "lod": "regional"
      }
    },
    "children_lods": {
      "regional": {
        "asset_id": "<sha256>",
        "media_type": "application/vnd.odin.boundary-pack+json;v=1",
        "byte_length": 45678,
        "vertex_count": 4321,
        "feature_count": 27,
        "role": "render",
        "lod": "regional"
      }
    }
  },
  "containment": {
    "asset_id": "<sha256>",
    "media_type": "application/vnd.odin.boundary+json;v=1",
    "byte_length": 23456,
    "vertex_count": 2048,
    "role": "containment",
    "max_error_m": 50.0
  },
  "provenance_ref": "natural-earth-admin0+geoboundaries-gbopen-admin1"
}
```

`path` ist vollständig servervalidiert; URL/Assets liefern keine Parent-Kette. Bei
`children_available=true` liegt `preferred_lod` zwingend in `children_lods`; Pick-
LOD-Fallback ist verboten.

`containment` darf `null` sein und ist der einzige Descriptor für clientseitiges
Point-in-Boundary. Render-LODs ändern niemals die Datenmenge.

### 10.6 Geometry-Wire-Format

Assets enthalten weder beliebige GeoJSON-Properties noch URLs:

```ts
type Position2D = readonly [longitude: number, latitude: number];
type LinearRing = readonly Position2D[];
type PolygonCoordinates = readonly LinearRing[];

interface BoundaryGeometryV1 {
  readonly schema_version: 1;
  readonly geometry_type: "MultiPolygon";
  readonly polygons: readonly PolygonCoordinates[];
}

type BoundaryPackFeatureV1 =
  | {
      readonly kind: "scope";
      readonly scope_key: string;
      readonly label: string;
      readonly geometry: BoundaryGeometryV1;
    }
  | {
      readonly kind: "context";
      readonly feature_id: string;
      readonly label: string;
      readonly non_scope_reason: string;
      readonly geometry: BoundaryGeometryV1;
    };

interface BoundaryPackV1 {
  readonly schema_version: 1;
  readonly parent_scope_key: string;
  readonly features: readonly BoundaryPackFeatureV1[];
}
```

`BoundaryPackV1` trägt keine `catalog_revision`: Sein SHA-256 fließt bereits in den
Manifest-Hash. Asset-ID, Manifest und Scope-Bundle-/HTTP-Kontext binden die Revision
ohne Selbstreferenz.

Jedes Asset wird vor Cesium-Konvertierung gegen Schema, Scope-Key-Grammatik,
Koordinatenbereiche, Ringabschluss, Ringgröße, Featurezahl, Vertexzahl und Bytebudget
validiert. Labels sind 1–120 Unicode-Codepoints und werden nur als Text gerendert;
`non_scope_reason` ist eine geschlossene Reason-Code-Enum, kein HTML-/Promptfeld.

V1 nutzt keine neue Schema-Library. Nach byte-gecapptem Fetch gilt
`const raw: unknown = JSON.parse(text)`. `isRecord`, `expectExactKeys`,
`expectFiniteNumber` und `expectString` dekodieren Metadaten; ein
iterativer Walker zählt Features/Ringe/Vertices und bricht am ersten Budgetverstoß
ab. `JSON.parse`-`any` gelangt nie per Cast in State/Cache. Tests mutieren jede Ebene
mit fehlenden, zusätzlichen, falschen und nicht-endlichen Werten.

Nur `kind="scope"` erhält Child-Fill und Pick-ID. Reviewtes `kind="context"` darf
policyabhängig nicht pickbar umrissen werden, aber weder Drill-Affordance noch Query-
Scope besitzen. Jeder `scope_key` ist kanonischer direkter Manifest-Child; nur dieses
Feld speist `SpatialChildPickId`, nie ein Frontend-Crosswalk.

### 10.7 HTTP-Caching

- Content-addressed Asset: `Cache-Control: public, max-age=31536000, immutable`.
- `ETag` entspricht dem in Anführungszeichen gesetzten SHA-256.
- V1 liefert Spatial-Assets mit `Content-Encoding: identity`; dadurch bezeichnet
  `byte_length` exakt Wire- und kanonische JSON-Bytezahl. Kompressionsvarianten
  benötigen später einen eigenen Descriptor statt mehrdeutiger Längen/Hashes.
- Scope-/Catalog-Metadaten: `ETag`, kurze Revalidation (`max-age=60, must-revalidate`).
- Keine beliebigen Redirects; ein Asset bleibt same-origin.
- Asset-Responses setzen `Content-Length` und `Content-Type`; der Client vergleicht
  beides mit dem Descriptor. Fehlt/überschreitet die Länge, liest er nicht blind per
  `response.json()`, sondern bricht vor Body beziehungsweise beim Streaming-Hardcap ab.
- 404 für einen unbekannten Key darf clientseitig 30 Sekunden negativ gecacht werden.
- 409/5xx/Korruptionsfehler werden nicht negativ gecacht.

### 10.8 Backend-Modelle

Neue zentrale Modelle in `app/models/spatial.py`:

```py
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

ScopeKey = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9:._-]+$",
    ),
]

CatalogRevision = Annotated[
    str,
    StringConstraints(
        min_length=23,
        max_length=79,
        pattern=r"^spatial-v[0-9]+-[a-f0-9]{12,64}$",
    ),
]

DerivationRevision = Annotated[
    str,
    StringConstraints(
        min_length=30,
        max_length=96,
        pattern=r"^spatial-derive-v[0-9]+-[a-f0-9]{12,64}$",
    ),
]


class ScopeKind(StrEnum):
    WORLD = "world"
    COUNTRY = "country"
    ADMIN1 = "admin1"
    ADMIN2 = "admin2"


class SpatialScopeTokenV1(BaseModel):
    schema_version: Literal[1] = 1
    scope_key: ScopeKey
    kind: ScopeKind
    catalog_revision: CatalogRevision
    derivation_revision: DerivationRevision
    boundary_policy: str = Field(min_length=1, max_length=96)
    compatible_derivation_revisions: tuple[DerivationRevision, ...] = Field(
        min_length=1,
        max_length=8,
    )

    @model_validator(mode="after")
    def current_revision_must_be_compatible(self) -> "SpatialScopeTokenV1":
        if self.derivation_revision not in self.compatible_derivation_revisions:
            raise ValueError("derivation_revision must be compatible")
        if len(set(self.compatible_derivation_revisions)) != len(
            self.compatible_derivation_revisions
        ):
            raise ValueError("compatible derivation revisions must be unique")
        return self
```

Die lexikalische Constraint ist nur die erste Schranke.
`normalize_scope_key_candidate()` kanonisiert bekannte ISO-Segmente;
`parse_scope_key()` matched danach diese geschlossene V1-Tabelle und liefert
`ParsedScopeKey(kind, namespace, canonical_code)`:

```py
_SCOPE_KEY_PATTERNS: Final[tuple[tuple[ScopeKind, re.Pattern[str]], ...]] = (
    (ScopeKind.WORLD, re.compile(r"^world$")),
    (ScopeKind.COUNTRY, re.compile(r"^country:[A-Z]{3}$")),
    (ScopeKind.COUNTRY, re.compile(r"^country:m49:[0-9]{3}$")),
    (
        ScopeKind.COUNTRY,
        re.compile(r"^country:odin:[a-z0-9][a-z0-9._-]{0,79}$"),
    ),
    (
        ScopeKind.ADMIN1,
        re.compile(r"^admin1:iso3166-2:[A-Z]{2}-[A-Z0-9]{1,3}$"),
    ),
    (
        ScopeKind.ADMIN1,
        re.compile(r"^admin1:gbopen:[A-Za-z0-9._-]{1,80}$"),
    ),
    (
        ScopeKind.ADMIN2,
        re.compile(r"^admin2:[A-Za-z0-9._-]{1,24}:[A-Za-z0-9._-]{1,80}$"),
    ),
)
```

Kein Match liefert `INVALID_SCOPE_KEY/422`; erst nach erfolgreichem Parse bedeutet
Katalog-„nicht gefunden“ `UNKNOWN_SCOPE/404`. Frontend und Backend teilen
Testvektoren, keine Parserimplementierung.

Response-Modelle spiegeln das Wire-Format. `extra="forbid"` gilt für Build-Manifeste
und interne Tokens; Frontend-Decoding validiert öffentliche Responses explizit und
ignoriert nichts still.

Das Backend erzeugt die Compatibility-Liste aus dem Manifest; der Browser sendet sie
nicht. Sie enthält stabile Derivationsrevisionen aus
[§7.5](02-scope-identity-and-boundary-policy.md#75-katalogrevision-versus-daten-derivationsrevision),
keine Catalog-Releases. Intelligence validiert ohne Boundary-Auflösung Länge,
Eindeutigkeit, Syntax und Einschluss der aktuellen `derivation_revision`. Mehr als
acht Werte lassen den Build failen statt abgeschnitten zu werden.

### 10.9 Frontend-Catalog-Port und interne Resolve-Form

```ts
interface BaseAssetDescriptor {
  readonly assetId: string;
  readonly mediaType: string;
  readonly byteLength: number;
  readonly vertexCount: number;
  readonly featureCount?: number;
}

interface RenderAssetDescriptor extends BaseAssetDescriptor {
  readonly role: "render";
  readonly lod: "overview" | "regional" | "local";
}

interface ContainmentAssetDescriptor extends BaseAssetDescriptor {
  readonly role: "containment";
  readonly maxErrorMeters: number;
}

type AssetDescriptor = RenderAssetDescriptor | ContainmentAssetDescriptor;
type GeometryLod = RenderAssetDescriptor["lod"];
type AssetLodSet = Readonly<Partial<Record<GeometryLod, RenderAssetDescriptor>>>;

interface ResolvedPresentationInput {
  readonly mode: "boundary";
  readonly scopeKey: ScopeKey;
  readonly catalogRevision: string;
  readonly preferredLod: GeometryLod;
  readonly outlineLods: AssetLodSet;
  readonly childrenLods: AssetLodSet;
  readonly cameraExtent: GeoExtent;
}

type ResolvedPresentation =
  | ResolvedPresentationInput
  | {
      readonly mode: "semantic-only";
      readonly scopeKey: ScopeKey;
      readonly catalogRevision: string;
      readonly problem: ScopeProblem;
    };

interface ResolvedScope {
  readonly scope: ScopeSummary;
  readonly path: ScopePath;
  readonly query: SpatialQueryRef;
  readonly presentation: ResolvedPresentation;
  readonly containment: ContainmentAssetDescriptor | null;
}

interface SpatialCatalogPort {
  resolve(
    scopeKey: ScopeKey,
    catalogRevision: string | null,
    signal: AbortSignal,
  ): Promise<ResolvedScope>;
  prefetch(
    scopeKey: ScopeKey,
    catalogRevision: string,
    priority: "hover" | "anticipated",
    signal: AbortSignal,
  ): Promise<void>;
  rehydrate(
    scopeKey: ScopeKey,
    activeCatalogRevision: CatalogRevision,
    signal: AbortSignal,
  ): Promise<ResolvedScope>;
  dispose(): void;
}

interface BoundaryAssetLease {
  readonly asset: BoundaryGeometryV1 | BoundaryPackV1;
  release(): void;
}

interface BoundaryAssetStore {
  acquire(
    descriptor: AssetDescriptor,
    signal: AbortSignal,
  ): Promise<BoundaryAssetLease>;
}

type PointContainment = "inside" | "outside" | "boundary-uncertain";

type ContainmentSnapshot =
  | { readonly phase: "building" | "unavailable"; readonly stateRevision: number }
  | {
      readonly phase: "ready";
      readonly stateRevision: number;
      contains(longitude: number, latitude: number): PointContainment;
    };

interface SpatialContainmentPort {
  getSnapshot(): ContainmentSnapshot;
  subscribe(listener: () => void): () => void;
}
```

`HttpSpatialCatalog` und `MemorySpatialCatalog` sind die einzigen V1-Adapter. HTTP
nutzt feste `/api/spatial/...`-Pfade, validiert vor Cache-Aufnahme und erzwingt die
[§11.4 definierten Budgets](05-boundary-build-and-antimeridian.md#114-lod-und-harte-budgets).
Memory ermöglicht deterministische Deferred-Promise-/Race-Tests.

Der interne, ref-counted `BoundaryAssetStore` wird geteilt. `prefetch` gibt nach
Decode frei, `present` nach Primitive-`ready`; der LRU-Eintrag bleibt und wird mit
aktiver Lease nie evicted. Ein Memory-Store testet Release/Abort ohne WebGL.

`containment` ist kein Render-LOD. Der Adapter hält Boundary und RBush-Index des
committed Scope samt Katalogrevision. Commit invalidiert den alten Index als
`building`; strikte Punktlayer verbergen alte Resultate bis `ready`. Kamera/LOD
berühren ihn nie. `world` enthält jeden validen WGS84-Punkt synthetisch; ohne Asset
ist der Consumer `unsupported`, nie BBox-Fallback.

`SpatialContainmentPort` dient nur registrierten Punktlayer-Adaptern. Ein Punkt ist
`boundary-uncertain`, wenn sein geodesischer Kantenabstand höchstens
`maxErrorMeters + epsilon` beträgt: strict schließt und zählt ihn, `dim-outside` darf
ihn markieren. Er wird nie in Neo4j/Qdrant-Keys zurückgeschrieben.

Initiale Hydration sendet `catalogRevision=null` und erhält die aktive Revision; späteres
`enter`/`ascend`/`prefetch` pinnt die committed Query-Revision. Ein Deployment mischt
damit nicht Country A und Admin-1 B. Bei 409 entscheidet sichtbares `rehydrate` über
die strukturierte aktive Revision; ohne Erfolg bleiben Adapter, Query und Router-
State unverändert, ohne heimlichen Retry.

### 10.10 Backend-Lifecycle

- `config.py` erhält `spatial_catalog_path` mit lokalem Default unter
  `/app/data/spatial`, `spatial_asset_max_concurrency=8` und einen kleinen validierten
  Acquire-Timeout; keine externe URL und kein Secret im Code.
- Der FastAPI-Lifespan erzeugt einmal `SpatialCatalogLoader` und legt ihn in
  `app.state.spatial_catalog` ab, analog zum vorhandenen Recon-Manifest-Lifecycle.
- Startup validiert Manifest-/Attributionsschema, den revisionsbildenden
  `attribution_sources_sha256`, Revisionshash, relative Assetpfade, deklarierte
  Dateigrößen und active/previous. Asset-Inhaltshashes
  werden im Build vollständig und im Backend spätestens beim ersten Serve geprüft;
  ein erfolgreicher Check wird pro unveränderlichem Asset gecacht.
- Manifest-/Hash-Datei-I/O läuft im Lifespan beziehungsweise beim ersten Serve über
  `asyncio.to_thread`; Request-Handler blockieren den Event Loop nicht. Externe HTTP-
  Zugriffe existieren in diesem Runtime-Pfad nicht.
- Ein kaputter/fehlender Katalog oder ungültige Attribution lässt Health und andere
  Routen intakt, setzt Spatial aber auf unavailable; Spatial-Routen antworten 503.
- Router wird unter dem bereits zentralen `/api`-Prefix registriert.
- Der Asset-Handler löst die Datei ausschließlich über das validierte Manifest auf und
  übernimmt die vorhandene immutable/range-fähige Cache-Header-Logik aus
  `app/static/cached_static.py`, statt einen zweiten Cache-Mechanismus zu erfinden.
- Asset-Reads laufen durch ein vom Loader besessenes `asyncio.Semaphore`. Kann der
  Handler innerhalb des konfigurierten Timeouts keinen Slot erhalten, öffnet er keine
  Datei und antwortet `429 ASSET_BUSY` mit `Retry-After: 1`. Der Slot wird in `finally`
  freigegeben; Cancellation und Client-Disconnect dürfen ihn nicht leaken.
- Shutdown gibt Loader-Caches und offene File-Handles deterministisch frei.

---
