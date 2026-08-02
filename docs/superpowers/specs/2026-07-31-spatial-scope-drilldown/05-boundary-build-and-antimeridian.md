# Teil-Spec 05 — Boundary-Build und Antimeridian

> **Parent:** [Spatial-Scope-Index](../2026-07-31-spatial-scope-drilldown-design.md)
>
> **Normativer Besitz:** Quelldaten, Source Lock, deterministischer Offline-Build,
> Topologie, Simplification, LOD-/Asset-Budgets und Antimeridian-Normalform.
>
> **Voraussetzungen:** [02 — Scope-Identität](02-scope-identity-and-boundary-policy.md)
> und [04 — Catalog-Verträge](04-spatial-catalog-contracts.md).

---

## 11. Boundary-Daten und Offline-Build

### 11.1 Quellenentscheidung

- Admin-0/World: vorhandenes Natural Earth; dessen offizielle Nutzungsbedingungen stellen die Daten in die Public Domain.
- Admin-1/Admin-2: geoBoundaries `gbOpen`, dessen offizielle API-Dokumentation CC BY 4.0 und administrative Ebenen ADM0–ADM5 ausweist.
- Identität/Crosswalk: eine separat reviewte, committed ODIN-Tabelle mit kanonischem
  ISO3/M49, Legacy-Aliases, Source-Codesystem und Sonderfallentscheidungen. Sie wird
  selbst gehasht und darf nicht implizit aus Natural-Earth-Displaynamen entstehen.
- Kein `gbAuthoritative` oder anderer Datensatz wird implizit angenommen; jeder Source-Lock nennt exakt Produkt, Release, URL, Lizenz und Hash.

Die Quellen sind Ausgangspunkt, keine unreviewte politische Wahrheit. `odin-reference-v1` dokumentiert die tatsächlich gewählte Representation.

Im Repo existiert bereits
`services/data-ingestion/infra_atlas/data/crosswalk.json`; es ist der Seed, nicht eine
zweite dauerhafte Registry. Slice 0 migriert/erweitert ihn zur kanonischen
`spatial_catalog/data/country_crosswalk.json`, passt `build_country_almanac.py` an und
entfernt den alten Pfad im selben Commit. Almanac und Spatial Build lesen danach exakt
dieselbe Datei und dieselben Tests. Kein Copy-and-diverge.

`services/frontend/public/country-endonyms.json._topoIndex` ist ausdrücklich kein
zweiter Crosswalk. Im neuen Spatial-Modus stammen pickbare `scope_key`-Werte direkt
aus dem validierten Catalog-Child-Pack. Die Datei bleibt während der Flag-Phase nur
im Legacy-Pfad; `_topoIndex`, `XKX`-Kopplung und der alte Country-Hit-Test werden im
Cleanup entfernt. Benötigte Namen/Kapitaldaten kommen danach aus dem bereits
serverseitig gebauten Country-Almanac und werden über den kanonischen Scope
aufgelöst, nicht zur Identitätserzeugung verwendet.

### 11.2 Source Lock

```json
{
  "schema_version": 1,
  "sources": [
    {
      "source_id": "natural-earth-admin0",
      "release": "<pinned release>",
      "url": "<exact immutable or archived URL>",
      "sha256": "<64 hex>",
      "license_id": "public-domain",
      "attribution": "Natural Earth"
    },
    {
      "source_id": "geoboundaries-gbopen-admin1",
      "release": "<pinned release>",
      "url": "<exact release URL>",
      "sha256": "<64 hex>",
      "license_id": "CC-BY-4.0",
      "attribution": "geoBoundaries / William & Mary geoLab"
    },
    {
      "source_id": "odin-country-crosswalk",
      "release": "spatial-crosswalk-v1",
      "url": "repo:services/data-ingestion/spatial_catalog/data/country_crosswalk.json",
      "sha256": "<64 hex>",
      "license_id": "LicenseRef-ODIN-Reviewed-Crosswalk",
      "attribution": "see crosswalk provenance records"
    }
  ]
}
```

Der Lock wird vor Implementierung mit realen Release-Werten erzeugt und reviewed. Platzhalter dürfen nicht in einen produktiven Build gelangen.

### 11.3 Build-Pipeline

Zielverzeichnis für Code:

```text
services/data-ingestion/spatial_catalog/
  __init__.py
  __main__.py
  catalog-plan.json
  models.py
  source_lock.py
  compiler.py
  normalize.py
  topology.py
  lod.py
  emit.py
  audit.py
```

CLI-Vertrag:

```bash
uv run python -m spatial_catalog fetch --source-lock <path> --cache-dir <path>
uv run python -m spatial_catalog build --source-lock <path> --out <path> --policy odin-reference-v1
uv run python -m spatial_catalog verify --catalog <path>
uv run python -m spatial_catalog audit --catalog <path> --report <path>
```

`fetch` ist die einzige netzwerkfähige Phase und nie Teil eines Service-Starts. `build`, `verify` und `audit` laufen offline aus hash-verifizierten Eingaben.

`catalog-plan.json` ist die reviewte Coverage-Policy, nicht ein verstecktes Python-
Array. Es nennt pro Country-Scope die maximal gebaute Ebene, gewünschte Source-
Representation, Aktivierungsstatus und `client_strict_containment_required`. V1
enthält Admin-1 zunächst nur für explizit priorisierte Theater; alle Admin-0-Scopes
bleiben global verfügbar. Ein Country ohne gebautes Admin-1 meldet
`children_available=false` und zeigt keine tote Drill-Affordance.

Normative Reihenfolge:

1. Source Lock und SHA-256 verifizieren.
2. Eingabeformat strikt parsen; jede Geometrie muss entweder einen kanonischen Scope-
   Key oder einen explizit reviewten `non_scope_feature`-Record mit Begründung erhalten.
3. Rohcodes plus `source_country_code_system` erhalten.
4. Country-Crosswalk aus einer reviewten Tabelle anwenden; keine Namensheuristik zur Laufzeit.
5. Scope-Key und kanonische Parent-Lineage erzeugen.
6. Koordinaten normalisieren, auf eine pro LOD festgelegte Dezimalpräzision
   quantisieren, direkt aufeinanderfolgende Duplikate entfernen und Ringe schließen.
   Outer-Ringe werden CCW, Holes CW kanonisiert; jeder Ring besitzt danach mindestens
   vier Positionen inklusive Closure.
7. Selbstüberschneidende/degenerierte Ringe und verwaiste Holes als Build-Fehler oder
   expliziten Audit-Drop mit Source-Feature-ID behandeln; nichts still reparieren.
8. Antimeridian-Geometrien splitten beziehungsweise kontinuierlich unwrapen und Holes
   demselben resultierenden Polygonteil zuordnen.
9. Vollauflösende kanonische Geometrie auf endliche Werte, Range, Ring-Closure,
   Orientation, Self-Intersection und nichtleere Fläche validieren.
10. Daraus eine eigene topology-preserving Containment-Repräsentation mit sechs
    Dezimalstellen, gemessenem `max_error_m <= 50` und Unsicherheitsband erzeugen.
    Sie darf vereinfacht sein, ist aber niemals eine Render-LOD. Passt ein als
    `client_strict_containment_required` markierter Scope nicht in die Budgets,
    stoppt der Build; nur optionale Scopes dürfen sichtbar `unsupported` bleiben.
11. LOD-Varianten topology-aware erzeugen; gemeinsame Grenzen müssen aus gemeinsamen Arcs entstehen, damit keine sichtbaren Risse entstehen.
12. Innerhalb eines Scope-Bundles Parent-Outline und Child-Pack aus demselben
    Topologiegraph ableiten. Wo vollständige Children vorliegen, ist die Parent-
    Outline deren policy-konformer Dissolve statt einer unabhängig vereinfachten
    zweiten Grenze.
13. Asset- und Pack-Budgets prüfen.
14. JSON mit sortierten Keys und stabiler Float-Normalisierung deterministisch serialisieren.
15. Asset-Hash berechnen; Manifest sortiert emittieren.
16. `derivation_revision` aus kanonischem Crosswalk, Scope-Lineage und den tatsächlich
    für Assignment verwendeten Containment-Artefakten ableiten. Labels, Attribution
    und Render-LOD gehen nicht ein; identischer Fingerprint ist expliziter Carry-forward.
17. Katalogrevision aus dem vollständigen inhaltsstabilen Manifest-Hash ableiten.
    Volatile Build-Zeitstempel gehen nicht in den Hash ein.
18. Einen zweiten Build aus denselben Inputs ausführen und Bytegleichheit beider
    Revisionen sowie aller Artefakte prüfen.

Ein `BoundaryPackV1` enthält dabei keine Katalogrevision in seinen eigenen Bytes. Der
Pack-Hash wird vom revisionsbildenden Manifest gebunden; eine eingebettete Revision
würde einen kryptographischen Selbstbezug aus Asset-Hash und Manifest-Hash erzeugen.

Der World-Overview darf Natural Earth verwenden, während ein betretenes Country für
Admin-1 auf die gepinnte geoBoundaries-Representation verfeinert. Dieser bewusste
Source-/LOD-Wechsel steht in der Provenance; innerhalb der gleichzeitig sichtbaren
Parent-/Child-Geometrie werden jedoch nie unabhängig widersprechende Kanten gemischt.

Für die topology-aware Simplification ist ein offline-only, exakt gepinntes Tool zu wählen. Mapshaper ist der bevorzugte Kandidat, weil seine offizielle Dokumentation topology-preserving Simplification und gewichtete Visvalingam-Verfahren beschreibt. Exakte Version, Lock und Prüfsumme sind ein Slice-0-Gate. ODIN versioniert dafür ein einziges gehashtes Offline-Archiv mit Mapshaper und der vollständigen, für den GeoJSON-Compilerpfad benötigten JavaScript-Abhängigkeitsclosure samt Lizenzmanifest; es gibt keine ungepinnte `npx latest`-Ausführung und keinen Paketdownload während des Builds. Eine eingecheckte Regenerierungsprozedur lädt ausschließlich die exakten Manifest-Versionen, verifiziert die npm-`integrity` jedes Upstream-Archivs selbst und muss das Offline-Archiv byteidentisch zum Source-Lock reproduzieren.

Node ist eine explizite Build-Host-Abhängigkeit des Compilers, keine Abhängigkeit eines Runtime-Service. Vor dem Entpacken oder Ausführen von Mapshaper prüft der Adapter die reale Ausgabe von `node --version` gegen `node_engine` und ruft den geprüften Node-Pfad direkt auf statt über den Entrypoint-Shebang. Die konkrete Node-Version steht in `build-provenance.json`; dieser Report bildet die Katalogrevision nicht mit. Das Bytegleichheits-Gate gilt für denselben verifizierten Toolchain-Satz. Produktions-Wheel und Ingestion-Image enthalten weder Spatial-Compiler noch Shapely, Node oder das Offline-Archiv.

### 11.4 LOD und harte Budgets

Initiale Gates, später nur benchmarkgestützt änderbar:

| LOD | Zweck | Dezimalstellen | Max. Boundary-Fehler | Max. Vertices/Pack |
|---|---|---:|---:|---:|
| `overview` | Welt/ferne Ansicht | 4 | 10 km | 12.000 |
| `regional` | Country/Admin-1 | 5 | 2 km | 50.000 |
| `local` | nahe Admin-Grenzen | 6 | 250 m | 120.000 |

Zusätzliche Limits:

- maximal 256 Child-Features pro V1-Pack;
- maximal 4 MiB kanonisches JSON/Wire beziehungsweise 16 MiB geschätzter dekodierter
  Objekt-Heap pro Asset;
- maximal 2.048 Ringe und 16.384 Vertices pro einzelnem Ring;
- keine Koordinate außerhalb `lon [-180,180]`, `lat [-90,90]` nach Normalisierung;
- keine Scope-Lineage tiefer als vier aktive Kinds;
- maximal 25 MiB committed Seed-Katalog ohne separate Artefakt-/LFS-Entscheidung.

Diese Werte sind vorläufige V1-Gates, keine ungemessenen Naturkonstanten. Slice 0
erzeugt `containment-feasibility.json` mit zwei expliziten Bereichen:

- `containment` deckt alle verpflichtenden Theater und die zehn nach Roh-Ringzahl
  größten Admin-0-Features des gelockten Inputs ab. Pro Feature stehen Source-/
  Normalform-Bytes, Ring-/Vertexzahlen, größter Ring, Wire-/Heap-Schätzung und
  gemessener Maximalfehler.
- `world_child_packs` misst jede emittierte World-`children_lods`-Variante, insbesondere
  `preferred_lod`, im tatsächlichen `BoundaryPackV1`-Wire-Format. Erfasst werden LOD,
  Asset-ID, Featurezahl, kanonische Wire-Bytes, dekodierte Heap-Schätzung, größter
  Ring und serialisierte Vertex-Vorkommen. Der Vertexzähler läuft nach Arc-Auflösung,
  zählt Ring-Closure und wiederholte gemeinsame Grenzen und ist exakt derselbe Zähler
  wie im Asset-Descriptor und Build-Gate; TopoJSON-Quellpunkte sind keine Ersatzmetrik.

Die Gates werden erst nach diesem Report freigegeben. Überschreitet ein Pflichtscope
4 MiB, 16 MiB Heap oder 16.384 Vertices pro Ring, wird vor Slice 3 Format,
Segmentierung oder Budget neu entschieden. Dasselbe gilt, wenn ein World-Child-Pack
das Feature-, Wire-, Heap- oder zum jeweiligen LOD gehörende Pack-Vertex-Limit
verletzt. Slice 0 bleibt rot; die Capability degradiert nicht still und der Build
verschiebt den Fehler nicht bis zum Cesium-Slice.

Überschreitet ein Admin-2-Gebiet die Featuregrenze, wird Admin-2 dort nicht aktiviert. Paging oder räumliches Tiling ist ein eigener späterer Vertrag und wird nicht heimlich in V1 improvisiert.

Der Simplifier muss Vertex- **und** Error-Budget erfüllen. Shared Junctions,
Antimeridian-Schnittpunkte, Enklaven-/Exklaven-Anker und policy-markierte Inseln sind
protected. Erfüllt keine Simplification beide Gates, schlägt der Build fehl oder der
Katalogplan deaktiviert diese Tiefe; er erhöht nicht still den Fehler. Der Audit-
Report enthält pro Asset Original-/Output-Vertices, maximale gemessene Abweichung,
entfernte Degenerate-Ringe und protected-feature count.

„Boundary-Fehler“ ist die maximale geodesische Originalpunkt-zu-vereinfachtem-Segment-
Abweichung aus dem Audit, nicht eine Grad-Toleranz. Das Containment-Ergebnis
`boundary-uncertain` verwendet genau dieses Fehlerband. Es misst damit ausschließlich
die Abweichung zur gelockten Quellgeometrie. Insbesondere bedeutet `max_error_m: 0`
keine metergenaue kartografische Quelle; Quellmaßstab und Quellgenauigkeit sind davon
unabhängig. Der Feasibility-Report nennt diese Semantik maschinenlesbar. Dadurch
bleibt das Gate über Breitengrade hinweg vergleichbar und behauptet für grenznahe
Punkte keine falsche Exaktheit.

### 11.5 Antimeridian-Normalform

Intern verwendet ODIN keine mehrdeutige „west > east“-BBox als Domänenmodell, sondern null, einen oder zwei nicht-wrapende Longitude-Spans:

```ts
interface LongitudeSpan {
  readonly west: number; // -180 <= west <= east <= 180
  readonly east: number; // 180 is allowed only as a span boundary sentinel
}

type GeoExtent =
  | { readonly kind: "world" }
  | {
      readonly kind: "segments";
      readonly south: number;
      readonly north: number;
      readonly longitude: readonly [LongitudeSpan] | readonly [LongitudeSpan, LongitudeSpan];
    };
```

Die minimale Längengradabdeckung wird über die größte Lücke auf dem Longitude-Kreis
und deren Komplement berechnet, nicht über naives `min/max`. Ein nicht-globaler Polar-
Scope darf einen vollen Longitude-Span `[-180,180]` bei eingeschränkter Latitude
besitzen. Pflichtfixtures: Fiji, Aleuten, Russland, Antarctica/Pol, Punkte `179/-179`,
MultiPolygon, Löcher und `world`.

Vendor-Adapter übersetzen diese Normalform:

- vorhandene Timeline-Legacy-BBox: ein Span oder `west > east` für zwei Spans;
- Neo4j: ein oder zwei statische `point.withinBBox`-Zweige;
- Qdrant: ein Geo-Bounding-Filter oder OR aus zwei Geo-Bounding-Filtern;
- Cesium-Kamera: BoundingSphere aus kartesischen Punkten, nicht naive Longitude-Mitte.

Für clientseitigen Point-Hit-Test erzeugt ein Scope mit zwei Longitude-Spans zwei
RBush-Nodes, die auf dasselbe Feature zeigen. Kandidaten werden vor dem eigentlichen
Ring-Test per `scopeKey` dedupliziert. Der Ring-Test unwrapt Query-Longitude und Ring
in dieselbe kontinuierliche Domäne; erst dann gelten Outer/Hole-Ray-Casts. Dadurch
wird weder ein fast weltgroßer BBox-Node erzeugt noch ein Dateline-Feature doppelt
zurückgegeben.

---
