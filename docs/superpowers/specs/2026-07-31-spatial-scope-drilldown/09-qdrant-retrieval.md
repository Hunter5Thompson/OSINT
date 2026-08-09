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
spatial_about_scope_revision_tokens       keyword[]
spatial_occurrence_scope_revision_tokens  keyword[]
geo                               geo point or geo point[]
spatial_basis                     keyword[]
spatial_precision                 keyword
spatial_catalog_revision          keyword
spatial_projection_revision       keyword
spatial_derivation_version        keyword
spatial_conflict                  bool
spatial_conflict_scope_keys       keyword[]
source_country_code               keyword
source_country_code_system        keyword
country_iso3                      keyword
admin1_code                       keyword
```

`about` und `occurrence` werden absichtlich in getrennten Feldern gespeichert. Ein
Bericht über Ukraine und ein Sensorereignis in Ukraine sind nicht dieselbe Relation.
Ein Dokument kann mehrere About-Scopes, ein Punkt-Ereignis mehrere Ancestor-Scopes
besitzen.

Jedes filterbare Arrayelement ist ein atomares, versioniertes Scope-/Revisionspaar:

```text
sr1|<canonical non-global ScopeKey>|<DerivationRevision>
```

`|` ist sowohl in der ScopeKey- als auch in der Derivationsrevisionsgrammatik
verboten. Das Encoding ist deshalb injektiv: Ein gültiger Token zerfällt eindeutig
in Prefix, Scope-Key und genau dessen Revision. Ein neues Eingabealphabet benötigt
eine neue Tokenversion; ein Parser darf `sr1` nicht heuristisch erweitern.

`spatial_catalog_revision` ist Audit-Provenance des letzten Laufs.
`spatial_projection_revision` ist ein stabiler Job-/Idempotenzfingerprint aus
Token-Vertrag, Deriver-Version, About-Gate-Policy und der kanonisch sortierten
Scope→Derivationsrevisionsmenge. Er ist **keine** fachliche Filterdimension. Ein
Catalog-Carry-forward mit identischer Scope→Revision-Menge behält denselben
Projektionsfingerprint. `spatial_derivation_version` bezeichnet die Version des
Normalizer-/Projector-Codes. Diese Felder sind nicht austauschbar.

Einen Qdrant-weiten scalar `spatial_derivation_revision` gibt es nicht: Schon ein
einzelnes Child-Assignment besitzt für Parent und Child unterschiedliche Revisionen,
und ein About-Dokument kann mehrere terminale Scopes besitzen. Die jeweilige
Derivationsrevision lebt ausschließlich im atomaren Pair-Token und zusätzlich im
nicht indexierten Audit-Feld `spatial_derivations`.

Ableitungsregeln:

- `occurrence` entsteht nur aus einer strukturierten Event-/Sensor-Location oder
  einer belastbaren Koordinate plus Boundary-Lookup; eine bloße Country-Erwähnung
  reicht nicht.
- `about` entsteht aus explizit extrahierten/geprüften Geo-Entitäten mit Provenance,
  nicht aus einem ungeprüften Substring-Match.
- Eine probabilistische/LLM-extrahierte About-Entität wird erst nach eindeutigem
  Alias-Crosswalk und einem versionierten Confidence-Gate in das filterbare Pair-Array
  übernommen. Unterhalb des Gates bleibt sie nur in `spatial_derivations` für Audit;
  der deterministische Writer entscheidet, nicht das Retrieval-LLM.
- Für einen bestätigten Child-Key werden dessen kanonische **nicht-globalen**
  Ancestors materialisiert, jeder mit der Derivationsrevision genau dieses Scopes.
  Damit funktionieren Country-Queries ohne Runtime-Hierarchiejoin. `world` bleibt
  implizit: globale Queries setzen ohnehin keinen Spatial-Filter.
- Widersprüchliche Ableitungen setzen einen Conflict-Status und werden nicht in den
  strikten Pair-Arrays publiziert.
- Mehrere Ableitungsbasen werden als Keyword-Liste und zusätzlich in einem nicht
  indexierten Audit-Feld `spatial_derivations` mit Relation, Scope-Key, Basis und
  Confidence gespeichert. Der Retrieval-Filter vertraut nur den reviewten Pair-Arrays.
- `spatial_catalog_revision` und `spatial_projection_revision` sind reine Provenance
  beziehungsweise Jobsteuerung. Der Filter erzeugt für den angefragten Scope genau
  einen Pair-Token je Wert seiner aktiven Compatibility-Menge; inkompatible Records
  zählen als stale/partial.
- Ein Re-Enrichment ersetzt alle `spatial_*`-Felder eines Qdrant-Points atomar; es
  mischt niemals Pair-Arrays und Projektionsprovenance verschiedener Läufe.
- Eine neue scope-spezifische Derivationsrevision ändert den Projektionsfingerprint
  und triggert denselben wiederkehrenden Dry-run/Apply/Coverage-Workflow wie Neo4j.
  Ein Catalog-Carry-forward mit vollständig unveränderter Scope→Revisionsmenge
  schreibt den Corpus nicht neu.

Beispiel für ein punktgenaues Event in Admin-1:

```json
{
  "spatial_about_scope_revision_tokens": [],
  "spatial_occurrence_scope_revision_tokens": [
    "sr1|country:UKR|spatial-derive-v1-d30efa07e141",
    "sr1|admin1:iso3166-2:UA-14|spatial-derive-v1-4d1de888e0c7"
  ],
  "geo": { "lon": 37.8, "lat": 48.0 },
  "spatial_basis": ["coordinate"],
  "spatial_precision": "point",
  "spatial_catalog_revision": "spatial-v1-e76a16bff799",
  "spatial_projection_revision": "spatial-projection-v1-1f7233edbacc",
  "spatial_derivation_version": "spatial-deriver-v1",
  "spatial_conflict": false,
  "spatial_conflict_scope_keys": []
}
```

### 16.2 Payload-Indizes

`PAYLOAD_INDEXES` erhält:

```py
PAYLOAD_INDEXES.update({
    "spatial_about_scope_revision_tokens": "keyword",
    "spatial_occurrence_scope_revision_tokens": "keyword",
    "geo": "geo",
    "spatial_basis": "keyword",
    "spatial_precision": "keyword",
    "spatial_catalog_revision": "keyword",
    "spatial_projection_revision": "keyword",
    "spatial_derivation_version": "keyword",
    "spatial_conflict": "bool",
    "spatial_conflict_scope_keys": "keyword",
})
```

Das sind weiterhin zehn Spatial-Indizes. Die zwei Pair-Token-Indizes ersetzen die
unkorrelierten Scope-Key-Indizes; der Projektionsindex ersetzt den sachlich falschen
scalar Derivationsindex. Indizes werden ausschließlich über den vorhandenen
autorisierten Migration-/Doctor-Pfad erzeugt, nicht während Search und nicht
beiläufig durch einen Writer. Sie werden vor der räumlichen Reindexierung angelegt.

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
_RELATION_FIELDS = {
    RetrievalSpatialRelation.ABOUT: "spatial_about_scope_revision_tokens",
    RetrievalSpatialRelation.OCCURRENCE: "spatial_occurrence_scope_revision_tokens",
}


def _scope_revision_tokens(token: SpatialScopeTokenV1) -> list[str]:
    return [
        encode_scope_revision_token(token.scope_key, revision)
        for revision in token.compatible_derivation_revisions
    ]


def _relation_condition(
    field: str,
    token: SpatialScopeTokenV1,
) -> FieldCondition:
    return FieldCondition(
        key=field,
        match=MatchAny(any=_scope_revision_tokens(token)),
    )


def compile_qdrant_scope_filter(
    token: SpatialScopeTokenV1,
    relation: RetrievalSpatialRelation,
) -> Filter | None:
    if token.kind is ScopeKind.WORLD:
        return None

    about = _relation_condition(_RELATION_FIELDS[RetrievalSpatialRelation.ABOUT], token)
    occurrence = _relation_condition(
        _RELATION_FIELDS[RetrievalSpatialRelation.OCCURRENCE], token
    )
    relation_condition: FieldCondition | Filter
    if relation is RetrievalSpatialRelation.ABOUT:
        relation_condition = about
    elif relation is RetrievalSpatialRelation.OCCURRENCE:
        relation_condition = occurrence
    else:
        relation_condition = Filter(should=[about, occurrence])

    non_conflict = FieldCondition(
        key="spatial_conflict",
        match=MatchValue(value=False),
    )
    return Filter(must=[relation_condition, non_conflict])


def combine_filters(base: Filter, spatial: Filter | None) -> Filter:
    return base if spatial is None else Filter(must=[base, spatial])
```

Die verschachtelte `Filter`-Komposition ist wichtig: sie verändert weder `should`-
Semantik noch Must-Not-Regeln der vorhandenen Analysis-/Realtime-Corpus-Policy und
mutiert deren Objekt nicht. Dieselbe Funktion kombiniert beide Lanes.

- `ABOUT`: Match auf `spatial_about_scope_revision_tokens`.
- `OCCURRENCE`: Match auf `spatial_occurrence_scope_revision_tokens`.
- `EITHER`: OR aus beiden, innerhalb eines verschachtelten Filters, der die bestehende Corpus-Policy nicht aufweicht.
- `world`: kein räumlicher Must-Filter, aber `SpatialApplication(mode=global)` bleibt im Ergebnis.
- Nicht-globale Filter kombinieren den Scope-Key atomar mit jedem allowlisted Wert
  seiner kompatiblen Derivationsrevisionen. Ein vertauschtes Parent-/Child-Paar kann
  nicht matchen. Records ohne oder außerhalb dieser Menge werden nicht still
  akzeptiert und fließen in die Coverage-/Stale-Zählung ein.
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
