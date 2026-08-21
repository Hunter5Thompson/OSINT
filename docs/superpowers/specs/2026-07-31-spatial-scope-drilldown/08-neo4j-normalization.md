# Teil-Spec 08 — Neo4j-Normalisierung

> **Parent:** [Spatial-Scope-Index](../2026-07-31-spatial-scope-drilldown-design.md)
>
> **Normativer Besitz:** additives Location-Schema, räumliche Indizes,
> deterministischer Normalizer, Writer-Transaktion, Konfliktsemantik, Backfill und
> Coverage-Gate.
>
> **Voraussetzungen:** [02 — Scope-Identität](02-scope-identity-and-boundary-policy.md)
> und [04 — Catalog-Verträge](04-spatial-catalog-contracts.md).

---

## 15. Neo4j-Schema, Normalisierung und Backfill

### 15.1 Additive Location-Felder

Vorhandene Rohfelder bleiben erhalten. Additiv:

```text
Location.source_country_code
Location.source_country_code_system
Location.country_iso3
Location.admin1_code
Location.admin2_code
Location.country_scope_key
Location.admin1_scope_key
Location.admin2_scope_key
Location.geo                        point({longitude, latitude})
Location.spatial_basis              source|crosswalk|coordinate|manual
Location.spatial_precision          country|admin1|admin2|point
Location.spatial_catalog_revision
Location.spatial_derivation_revision
Location.spatial_conflict           boolean
Location.spatial_conflict_scope_keys list<string>
```

Ein Record kann `country_scope_key` ohne Punkt besitzen. Er ist für einen Country-Scope semantisch nutzbar, aber nicht automatisch für Admin-1. Eine Country-Koordinate am Centroid wird niemals erfunden, um Point-Coverage vorzutäuschen.

### 15.2 Indizes

Deterministische Migration:

```cypher
CREATE RANGE INDEX location_country_scope_derivation IF NOT EXISTS
FOR (l:Location) ON (l.country_scope_key, l.spatial_derivation_revision);

CREATE RANGE INDEX location_admin1_scope_derivation IF NOT EXISTS
FOR (l:Location) ON (l.admin1_scope_key, l.spatial_derivation_revision);

CREATE RANGE INDEX location_admin2_scope_derivation IF NOT EXISTS
FOR (l:Location) ON (l.admin2_scope_key, l.spatial_derivation_revision);

CREATE POINT INDEX location_geo IF NOT EXISTS
FOR (l:Location) ON (l.geo);
```

Der bereits vorhandene `location_geo`-Migrationssatz wird nicht dupliziert; seine Writer-Abdeckung wird geschlossen und die Migration konsolidiert.

### 15.3 Writer-Regel

Jeder Geo-Writer ruft einen gemeinsamen deterministischen Normalizer mit strukturiertem Input auf:

```py
class CountryCodeSystem(StrEnum):
    ISO2 = "iso2"
    ISO3 = "iso3"
    UN_M49 = "un-m49"
    GDELT_GEC = "gdelt-gec"
    NATURAL_EARTH_M49 = "natural-earth-m49"
    ODIN_SCOPE_KEY = "odin-scope-key"


class AdministrativeCodeSystem(StrEnum):
    ISO_3166_2 = "iso-3166-2"
    GEOBOUNDARIES = "geoboundaries"
    GDELT_ADM1 = "gdelt-adm1"
    ODIN_SCOPE_KEY = "odin-scope-key"


class RawLocationIdentity(BaseModel):
    country_code: str | None
    country_code_system: CountryCodeSystem | None
    source_country_name: str | None
    admin1_code: str | None
    admin1_code_system: AdministrativeCodeSystem | None
    admin2_code: str | None
    admin2_code_system: AdministrativeCodeSystem | None
    latitude: float | None
    longitude: float | None
```

Model-Validatoren verlangen Code/System jeweils gemeinsam und Latitude/Longitude
jeweils gemeinsam in Range. `0.0` wird per `is not None`, nie per Truthiness geprüft.
`(0,0)` wird weder als Fallback erzeugt noch pauschal verworfen; ein echter Source-
Punkt dort bleibt mit Provenance erhalten, während bestehende Null-Island-Audits
synthetische Defaults separat erkennen.

Output enthält Werte plus `basis`, `precision`, `conflict`. Kein freier Location-Name wird ohne reviewten Crosswalk zu einem Country-Key erhoben. Der Normalizer erzeugt keine Cypher-Strings; Writer binden die Werte an vorhandene Templates.

Bei coordinate-only Reverse-Lookup ist ein klarer Polygon-Interior-Treffer zuordenbar.
Liegt der Punkt auf einer geteilten Boundary (robuster geodesischer Epsilon-Test) und
trifft mehrere Children, wird kein lexikographischer Sieger erfunden: Der Record erhält
nur den eindeutig gemeinsamen Ancestor, `spatial_conflict=true` für die tiefere Ebene
und die Kandidaten in `spatial_conflict_scope_keys`; so kann jede betroffene Child-
Query ihren Conflict-Zähler bilden, ohne den Record als Treffer auszugeben. Ein
expliziter, gültiger Source-Admin-Code darf die
Geometrie-Ambiguität mit `basis=source-code` auflösen; der Widerspruch bleibt im Audit.

Scope-Keys, `geo`, Basis, Precision, Conflict, Audit-Katalogrevision und stabile
Derivationsrevision werden im selben parametergebundenen `SET` geschrieben. Ein
Teilfehler darf keine gemischte Revision auf dem Node hinterlassen; die Transaktion
wird zurückgerollt.

### 15.4 Backfill

- forward writers zuerst;
- Batchgröße konfigurierbar, Cursor stabil, Restart idempotent;
- `--dry-run` ist Pflicht vor `--apply`;
- Report: total, already-normalized, resolvable, unresolved, conflicting, invalid-coordinate, by-source/by-code-system;
- Apply schreibt nur Datensätze mit deterministischer Auflösung;
- Konflikte bleiben unverändert, setzen `spatial_conflict=true` und werden aus exakten Scope-Queries ausgeschlossen;
- kein Löschen alter Properties;
- Backup/Restore-Point vor Apply gemäß bestehender Graph-Operationspraxis.

Das ist kein Einmaljob. Erzeugt ein Catalog-Build eine neue
`spatial_derivation_revision`, legt die Pipeline automatisch je betroffener Source-
Lane einen restartbaren Re-Enrichment-Lauf an: Dry-run und Report, reviewtes Apply,
Coverage-Report, dann Exact-Promotion. Ein Katalog mit explizitem Carry-forward der
gleichen Derivationsrevision erzeugt keinen Rewrite. Cursor und Checkpoint enthalten
Lane, Ziel-Derivationsrevision und letzte stabile Record-ID; ein Neustart mischt keine
Revisionen.

### 15.5 Coverage-Gate

Exact wird pro Source-Lane aktiviert, wenn:

1. 100 % der Datensätze mit bereits vorhandenem, erkanntem Country-Code entweder deterministisch normalisiert oder explizit als Conflict klassifiziert sind;
2. 0 unbekannte Codes still auf einen Default fallen;
3. mindestens 95 % der nicht-konfliktären, country-addressable Records der Lane einen `country_scope_key` besitzen;
4. Query-Plan den vorgesehenen Index verwendet;
5. Response-Accounting in Fixture und Staging stimmt;
6. `excluded_stale_revision_count / addressable_records <= 1 %`; jeder Wert über null
   bleibt sichtbar, über 1 % blockiert die Exact-Promotion.

Gesamtcorpus-Coverage wird zusätzlich berichtet. Ein hoher Lane-Wert darf fehlende Geometadaten anderer Dokumente nicht verstecken.

---
