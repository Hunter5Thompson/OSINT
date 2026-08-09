# Teil-Spec 02 — Scope-Identität und Boundary-Policy

> **Parent:** [Spatial-Scope-Index](../2026-07-31-spatial-scope-drilldown-design.md)
>
> **Normativer Besitz:** `ScopeKey`, unterstützte Kinds, Lineage, politische
> Representation sowie Katalog- und Derivationsrevision.
>
> **Voraussetzung:** [01 — Architektur und Invarianten](01-architecture-and-invariants.md).
> Jeder Adapter muss diese Identität konsumieren und darf sie nicht lokal neu deuten.

---

## 7. Kanonische Identität und Boundary-Policy

### 7.1 `ScopeKey`

`ScopeKey` ist ein opaker stabiler Schlüssel. Nur der Parser im Spatial-Modul darf Präfixe interpretieren; UI-Caller dürfen niemals Codes per `split(":")` ableiten.

Zulässige Zielgrammatik:

```text
world
country:<ISO3>                       country:UKR
country:m49:<three digits>           country:m49:010
country:odin:<reviewed stable id>     country:odin:somaliland
admin1:iso3166-2:<code>              admin1:iso3166-2:UA-14
admin1:gbopen:<stable source id>     admin1:gbopen:...
admin2:<namespace>:<stable id>       admin2:gbopen:...
```

Validierung vor jedem Lookup:

```text
length: 1..128 bytes
characters: [A-Za-z0-9:._-]
forbidden: slash, backslash, percent after URL decode, whitespace, NUL
```

Weitere Invarianten:

- `world` ist der einzige Root und hat keinen Parent.
- ISO3 und ISO-3166-2 werden bei der Adaptergrenze uppercase kanonisiert; die URL wird
  bei Erfolg per React-Router-Replace auf die kanonische Form gebracht. Source-spezifische
  IDs wie `gbopen` bleiben case-sensitive und werden niemals umgeschrieben.
- Fallback-Namespaces sind Teil der Identität; ein GDELT/FIPS-Code darf niemals wie ISO3 aussehen und behandelt werden.
- `country:odin:*` ist ausschließlich für eine manuell reviewte, nicht aus Namen
  generierte Referenzidentität ohne passenden ISO3/M49-Key zulässig. Der Alias- und
  Dispute-Record ist Pflicht.
- Die Regex-Form `country:[A-Z]{3}` beweist nur Syntax. Der Katalog prüft zusätzlich
  gegen die gepinnte offizielle Code-Tabelle. Das im bestehenden Seed verwendete
  `XKX` wird nicht als offizielles ISO3 ausgegeben: die Policy legt einen kanonischen
  `country:odin:kosovo`-Scope fest; ein bereits persistiertes `country:XKX` kann als
  expliziter Legacy-Alias darauf aufgelöst werden. Antarctica wird über den vorhandenen
  M49-Key `country:m49:010` klassifiziert.
- Ein Scope-Key wird nicht aus einem Display-Namen erzeugt.
- Alias/Crosswalk-Wechsel zwischen Katalogrevisionen werden explizit gespeichert; IDs werden nicht still neu vergeben.

Ein historischer Fallback-Key kann als Alias auf einen später verfügbaren kanonischen
Key zeigen. Der Resolve-Response nennt dann `canonicalized_from`; Store und Query
committen ausschließlich den kanonischen Key. Bei Deep-Link-Hydration wird nur der
`scope`-Parameter per Router-Replace kanonisiert, damit alte Reports und Bookmarks
weiter funktionieren, ohne eine zweite semantische Identität zu erzeugen.

### 7.2 Unterstützte Kinds

Die geschlossene Menge lautet `world`, `country`, `admin1`, `admin2`. V1 aktiviert
`world`, `country` und ausgewählte `admin1`-Kataloge. `admin2` ist reserviert und wird
erst nach dem Cardinality-/Tiling-Gate aktiviert. `locality` und `aoi` benötigen
später eigene Semantik und werden nicht vorgetäuscht. Die einzige ausführbare
TypeScript-Deklaration lebt in `spatial/contracts.ts` und wird in
[§8.1](03-frontend-core-and-navigation.md#81-öffentliche-typen) gezeigt; andere Module
importieren beziehungsweise re-exportieren sie nur.

### 7.3 Identität ist nicht Geometrie

Ein Scope bleibt semantisch gültig, wenn seine Geometrie nicht geladen oder nicht verfügbar ist. Deshalb sind getrennt:

- `scope_key`: stabile semantische Identität;
- `catalog_revision`: unveränderliche Katalogversion;
- `boundary_policy`: benannte Darstellungs-/Quellenpolicy;
- `geometry_ref`: content-addressed Render-Asset;
- `presentation`: `boundary | semantic-only`.

Eine neue Boundary-Geometrie ändert die Katalogrevision, nicht zwangsläufig den Scope-Key.

### 7.4 Politische und disputed Geometrien

Der Name der Policy lautet bewusst `odin-reference-v1`, nicht „neutral“. Jeder Katalog führt mindestens:

```json
{
  "boundary_policy": "odin-reference-v1",
  "representation_id": "<source representation>",
  "dispute_status": "none|disputed|multiple-representations",
  "source_id": "natural-earth|geoboundaries-gbopen|...",
  "source_release": "<pinned release>",
  "license_id": "CC0-1.0|CC-BY-4.0|...",
  "attribution": "<reviewed text>"
}
```

Disputed Claims sind Daten mit Provenance und optionalen Darstellungsalternativen, keine fest codierten UI-Regeln. Es gibt insbesondere keine erzwungene Neun-Strich-Linie, keine implizite PRC-Position und kein nicht deaktivierbares Inset. Eine Darstellung mit politischer Aussage benötigt eine explizit reviewte Policy-Revision.

### 7.5 Katalogrevision versus Daten-Derivationsrevision

`catalog_revision` im Query-Token bezeichnet das vollständige Katalogartefakt, gegen
das Scope und Boundary aufgelöst wurden. `derivation_revision` bezeichnet dagegen den
stabilen Fingerprint genau der Crosswalk-/Containment-Eingaben, die materialisierte
Scope-Zuordnungen erzeugen. Ein reines Label-, Attribution- oder Render-LOD-Release
behält dieselbe Derivationsrevision und verbraucht keinen Kompatibilitätseintrag.

`derivation_revision` gehört semantisch zu genau einem kanonischen Scope-Assignment,
nicht pauschal zu einem Record. Sobald ein Child und seine Ancestors gemeinsam
materialisiert werden, muss die persistierte Filterrepräsentation deshalb jedes
`(scope_key, derivation_revision)`-Paar korreliert halten. Getrennte Scope- und
Revisionsarrays oder ein einziger recordweiter Scalar dürfen nicht als Exact-Vertrag
verwendet werden.

Neo4j-/Qdrant-Records speichern `spatial_catalog_revision` als Audit-Provenance des
letzten Enrichments. Qdrant speichert die Filterdimension in den versionierten,
relation-spezifischen Pair-Tokens aus Spec 09. Sein
`spatial_projection_revision` ist nur Job-/Idempotenzprovenance und keine fachliche
Compatibility-Dimension. Der bestehende Neo4j-Scalar
`spatial_derivation_revision` bezeichnet höchstens die Revision des terminal
ausgewählten Scopes. Ein Exact-Read darf ihn nur mit genau diesem Scope paaren;
Parent-Promotionen über tiefer aufgelöste Locations bleiben bis zu einem eigenen
gepaarten Neo4j-Vertrag geschlossen.

Query-Compiler vergleichen niemals die Katalogrevision oder den
Projektionsfingerprint eines Records mit der Request-Katalogrevision. Sie lösen die
Compatibility-Menge für den angefragten Scope auf und vergleichen ausschließlich
gegen die mit genau diesem Scope korrelierten Derivationsrevisionen.

Der Katalog führt deshalb eine explizite Kompatibilitätsmatrix:

```json
{
  "derivation_compatibility": {
    "country:UKR": {
      "catalog_revision": "spatial-v1-a1b2c3d4e5f6",
      "current": "spatial-derive-v1-112233445566",
      "compatible": [
        "spatial-derive-v1-112233445566",
        "spatial-derive-v1-aabbccddeeff"
      ],
      "carry_forward_from": "spatial-v1-998877665544"
    }
  }
}
```

Die Matrix wird pro kanonischem Scope aufgelöst; der Build darf Einträge intern über
identische Fingerprint-Gruppen deduplizieren. Eine Grenzänderung in einem anderen
Scope macht dadurch nicht pauschal den gesamten Altbestand inkompatibel.

- `carry_forward_from` ist nur zulässig, wenn der Build die für den jeweiligen
  Scope-Kind wirksamen Crosswalk- und Assignment-Artefakte bytegleich beziehungsweise
  semantisch gleich fingerprintet; ein Reviewer bestätigt den Audit-Diff.
- Geometrisch abgeleitete Admin-Zuordnungen werden nur kompatibel erklärt, wenn die
  betroffenen Parent-/Child-Grenzen semantisch unverändert sind.
- Inkompatibel abgeleitete Records werden bis zum Re-Enrichment ausgeschlossen und
  als `excluded_stale_revision_count` ausgewiesen.
- Fehlt eine explizite Aussage, gilt eine alte Derivationsrevision als inkompatibel.
  Es gibt keine automatische „wahrscheinlich gleich“-Annahme.
- Die Compatibility-Liste ist auf acht **Derivations-**, nicht Katalogrevisionen
  begrenzt. Der Build darf sie niemals abschneiden: Ein neunter Eintrag stoppt die
  Promotion und verlangt Re-Enrichment beziehungsweise eine reviewte Kompaktierung.
- Point-in-Boundary zur Request-Zeit verwendet immer die angeforderte, bediente
  Katalogrevision und benötigt deshalb keine historische Derivationsfreigabe.

Jede neue Derivationsrevision triggert wiederkehrende, restartbare Neo4j- und Qdrant-
Re-Enrichment-Jobs mit Dry-run, Apply und Coverage-Report. Die Exact-Aktivierung für
betroffene Scope-Kinds wartet auf deren Gate. Alle Consumer sehen dieselbe Request-
Katalogrevision und dieselbe kompatible Menge; die Datenebene legt zusätzlich offen,
wie viel Material stale blieb.

---
