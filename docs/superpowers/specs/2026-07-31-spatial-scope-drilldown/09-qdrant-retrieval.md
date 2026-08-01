# Teil-Spec 09 — Qdrant-Retrieval

> **Parent:** [Spatial-Scope-Index](../2026-07-31-spatial-scope-drilldown-design.md)
>
> **Normativer Besitz:** räumliche Payload-Felder, Indexmigration,
> relation-spezifischer Filter-Compiler, Corpus-Policy-Komposition und Partial
> Coverage.
>
> **Voraussetzungen:** [02 — Scope-Identität](02-scope-identity-and-boundary-policy.md)
> und [04 — Catalog-Verträge](04-spatial-catalog-contracts.md). Agent-Enforcement
> liegt in [10](10-munin-scope-enforcement.md).

---

## 16. Qdrant-Schema und Retrieval-Projektion

### 16.1 Payload-Felder

```text
spatial_about_scope_keys          keyword[]
spatial_occurrence_scope_keys     keyword[]
geo                               geo point or geo point[]
spatial_basis                     keyword[]
spatial_precision                 keyword
spatial_catalog_revision          keyword
spatial_derivation_revision       keyword
spatial_derivation_version        keyword
spatial_conflict                  bool
spatial_conflict_scope_keys       keyword[]
source_country_code               keyword
source_country_code_system        keyword
country_iso3                      keyword
admin1_code                       keyword
```

`about` und `occurrence` werden absichtlich getrennt. Ein Bericht über Ukraine und ein Sensorereignis in Ukraine sind nicht dieselbe Relation. Ein Dokument kann mehrere About-Scopes, ein Punkt-Ereignis mehrere Ancestor-Scopes besitzen.

`spatial_catalog_revision` ist Audit-Provenance des letzten Laufs,
`spatial_derivation_revision` der stabile Assignment-Fingerprint für Filter und
`spatial_derivation_version` die Version des Normalizer-Codes. Diese drei Felder sind
nicht austauschbar.

Ableitungsregeln:

- `occurrence` entsteht nur aus einer strukturierten Event-/Sensor-Location oder
  einer belastbaren Koordinate plus Boundary-Lookup; eine bloße Country-Erwähnung
  reicht nicht.
- `about` entsteht aus explizit extrahierten/geprüften Geo-Entitäten mit Provenance,
  nicht aus einem ungeprüften Substring-Match.
- Eine probabilistische/LLM-extrahierte About-Entität wird erst nach eindeutigem
  Alias-Crosswalk und einem versionierten Confidence-Gate in das filterbare Key-Array
  übernommen. Unterhalb des Gates bleibt sie nur in `spatial_derivations` für Audit;
  der deterministische Writer entscheidet, nicht das Retrieval-LLM.
- Für einen bestätigten Child-Key werden dessen kanonische **nicht-globalen**
  Ancestors materialisiert, damit Country-Queries ohne Runtime-Hierarchiejoin möglich
  sind. `world` bleibt implizit: globale Queries setzen ohnehin keinen Spatial-Filter.
- Widersprüchliche Ableitungen setzen einen Conflict-Status und werden nicht in den
  strikten Key-Arrays publiziert.
- Mehrere Ableitungsbasen werden als Keyword-Liste und zusätzlich in einem nicht
  indexierten Audit-Feld `spatial_derivations` mit Relation, Scope-Key, Basis und
  Confidence gespeichert. Der Retrieval-Filter vertraut nur den reviewten Key-Arrays.
- `spatial_catalog_revision` ist reine Provenance. Der Filter verwendet ausschließlich
  `spatial_derivation_revision` und akzeptiert nur Werte aus der im aktiven Katalog
  erklärten Compatibility-Menge; inkompatible Records zählen als stale/partial.
- Ein Re-Enrichment ersetzt alle `spatial_*`-Felder eines Qdrant-Points atomar; es
  mischt niemals Key-Arrays aus Revision A mit einem scalar Revision-Label B.
- Eine neue `spatial_derivation_revision` triggert denselben wiederkehrenden Dry-run/
  Apply/Coverage-Workflow wie Neo4j. Ein Catalog-Carry-forward mit unveränderter
  Derivationsrevision schreibt den Corpus nicht neu.

Beispiel für ein punktgenaues Event in Admin-1:

```json
{
  "spatial_occurrence_scope_keys": [
    "country:UKR",
    "admin1:iso3166-2:UA-14"
  ],
  "geo": { "lon": 37.8, "lat": 48.0 },
  "spatial_basis": ["source-coordinate", "catalog-containment"],
  "spatial_precision": "point",
  "spatial_catalog_revision": "spatial-v1-a1b2c3d4e5f6",
  "spatial_derivation_revision": "spatial-derive-v1-112233445566",
  "spatial_derivation_version": "spatial-deriver-v1",
  "spatial_conflict": false,
  "spatial_conflict_scope_keys": []
}
```

### 16.2 Payload-Indizes

`PAYLOAD_INDEXES` erhält:

```py
PAYLOAD_INDEXES.update({
    "spatial_about_scope_keys": "keyword",
    "spatial_occurrence_scope_keys": "keyword",
    "geo": "geo",
    "spatial_basis": "keyword",
    "spatial_precision": "keyword",
    "spatial_catalog_revision": "keyword",
    "spatial_derivation_revision": "keyword",
    "spatial_derivation_version": "keyword",
    "spatial_conflict": "bool",
    "spatial_conflict_scope_keys": "keyword",
})
```

Indizes werden ausschließlich über den vorhandenen autorisierten Migration-/Doctor-Pfad erzeugt, nicht während Search und nicht beiläufig durch einen Writer. Sie werden vor der räumlichen Reindexierung angelegt.

### 16.3 Deterministischer Filter-Compiler

```py
class RetrievalSpatialRelation(StrEnum):
    ABOUT = "about"
    OCCURRENCE = "occurrence"
    EITHER = "either"


def compile_qdrant_scope_filter(
    token: SpatialScopeTokenV1,
    relation: RetrievalSpatialRelation,
) -> Filter | None:
    # Returns only qdrant-client model objects built from allowlisted fields.
    ...
```

Codeform der V1-Projektion mit den lokal installierten qdrant-client-Modellen:

```py
def _scope_key_condition(field: str, scope_key: str) -> FieldCondition:
    return FieldCondition(key=field, match=MatchAny(any=[scope_key]))


def compile_qdrant_scope_filter(
    token: SpatialScopeTokenV1,
    relation: RetrievalSpatialRelation,
) -> Filter | None:
    if token.kind is ScopeKind.WORLD:
        return None

    about = _scope_key_condition(
        "spatial_about_scope_keys",
        token.scope_key,
    )
    occurrence = _scope_key_condition(
        "spatial_occurrence_scope_keys",
        token.scope_key,
    )
    relation_condition: FieldCondition | Filter
    if relation is RetrievalSpatialRelation.ABOUT:
        relation_condition = about
    elif relation is RetrievalSpatialRelation.OCCURRENCE:
        relation_condition = occurrence
    else:
        relation_condition = Filter(should=[about, occurrence])

    compatible = FieldCondition(
        key="spatial_derivation_revision",
        match=MatchAny(any=list(token.compatible_derivation_revisions)),
    )
    return Filter(must=[relation_condition, compatible])


def combine_filters(base: Filter, spatial: Filter | None) -> Filter:
    return base if spatial is None else Filter(must=[base, spatial])
```

Die verschachtelte `Filter`-Komposition ist wichtig: sie verändert weder `should`-
Semantik noch Must-Not-Regeln der vorhandenen Analysis-/Realtime-Corpus-Policy und
mutiert deren Objekt nicht. Dieselbe Funktion kombiniert beide Lanes.

- `ABOUT`: Match auf `spatial_about_scope_keys`.
- `OCCURRENCE`: Match auf `spatial_occurrence_scope_keys`.
- `EITHER`: OR aus beiden, innerhalb eines verschachtelten Filters, der die bestehende Corpus-Policy nicht aufweicht.
- `world`: kein räumlicher Must-Filter, aber `SpatialApplication(mode=global)` bleibt im Ergebnis.
- Nicht-globale Filter kombinieren den Scope-Key mit der allowlisted Menge
  kompatibler `spatial_derivation_revision`-Werte. Records ohne oder außerhalb dieser
  Menge werden nicht still akzeptiert und fließen in die Coverage-/Stale-Zählung ein.
- Der User-Query-Text und das LLM liefern weder Feldnamen noch Scope-Key.
- Antimeridian-BBox wird nur für explizite Geo-/AOI-Projektionen benötigt und als OR aus zwei nicht-wrapenden `GeoBoundingBox`-Filtern kompiliert.

Die bestehenden Analysis-/Realtime-Lanes behalten ihre Corpus-Policy. Spatial ist ein zusätzliches `must`, kein Ersatz und kein nachträgliches clientseitiges Aussortieren der Top-k.

### 16.4 Partial Coverage

Alte Payloads ohne räumliche Keys erscheinen in einem nicht-globalen, strikt gefilterten Resultat nicht. Die Search-Antwort enthält den zum Index-Build gehörenden Coverage-Snapshot pro Lane. Eine leere Antwort darf unterschieden werden in:

- keine semantischen Treffer innerhalb des Scope;
- Scope-Filter technisch nicht verfügbar;
- Scope-Coverage unzureichend/partial.

Keiner dieser Fälle darf eine zweite ungefilterte Suche auslösen.

Der Coverage-Snapshot weist den Stale-Anteil pro Lane aus. Jeder Wert über null ist
beobachtbar; über 1 % blockiert die Promotion einer neuen Exact-Capability und löst
den Re-Enrichment-Alarm aus.

---
