# Spatial Plan 07A — Qdrant Writer-/Lane-Inventur

**Datum:** 2026-08-10
**Scope:** Work Order 2; Code-Inventur, keine Live-Mutation

## Entscheidung

Plan 07A migriert genau zwei aktive Writer-Seams. Alle anderen Qdrant-Writer
bleiben fachlich sichtbar, werden aber nicht durch Ortsnamen-, Text- oder
Substring-Raten räumlich angereichert. Die maschinenlesbare Matrix liegt in
`contracts/qdrant-spatial-writer-lanes-v1.json`.

| Writer-Lane | Status | Relation | Zulässige Evidenz |
|---|---|---|---|
| `gdelt_raw_gkg` | unterstützt | `occurrence` | exakter Join von `linked_event_ids` auf kanonische Event-Parquetzeilen; ausschließlich strukturierte ActionGeo-Codes/Koordinaten |
| `notebooklm_claim` | unterstützt | `about` | exakte Claim→Entity-Zuordnung; typisierte Geo-Entität; eindeutiger reviewter Name-Crosswalk; versioniertes Confidence-Gate |
| `intelligence_legacy_indexer` | unavailable | keine | das Legacy-Feld `region` ist keine filterbare Evidenz |
| Legacy-Feed-Collector | unavailable | keine | in 07A existiert kein reviewter source-spezifischer Adapter |
| `suv_structured` | unavailable | keine | in 07A existiert kein reviewter Spatial-Adapter |

## Writer-Grenzen

Der GDELT-Qdrant-Writer bleibt von Neo4j unabhängig. Er liest GKG- und Event-Parquet
derselben vollständig persistierten Slice und verbindet ausschließlich exakte
kanonische Event-IDs. Titel, Themes, Personen-, Organisations- und Ortsnamenfelder
erzeugen keine Occurrence-Zuordnung.

Der NLM-Writer verwendet `Extraction.entities` für Typ und Confidence. Ein Name in
`Claim.entities_involved` muss exakt einer extrahierten Entität und anschließend
exakt einem Eintrag des reviewten Crosswalks entsprechen. Modell-generierte Aliase,
Claim-Text und Substrings sind keine Crosswalk-Quelle. Unterhalb des Gates oder bei
fehlender/eindeutigkeitsloser Zuordnung bleibt die Ableitung nur auditierbar und
nicht filterbar.

## Unsupported-Vertrag

Unsupported bedeutet nicht global und nicht stillschweigend erfolgreich. Neue
Writes über den Legacy-Intelligence-Indexer markieren die räumliche Ableitung als
`unavailable`; die übrigen vorhandenen Source-Lanes werden durch die eingecheckte
Matrix im späteren Coverage-Report als unavailable gezählt. Diese Inventur ist
keine Erlaubnis, die Collector in Work Order 2 opportunistisch umzubauen.

## TDD- und Verifikationsnachweis

Der erste Work-Order-2-Lauf schlug wie beabsichtigt fehl: `qdrant_spatial` und der
öffentliche Ancestor-/Revision-View existierten noch nicht, der GDELT-Writer nahm
keinen Spatial-Index an, NLM besaß keinen reviewten Crosswalk-Seam und der
Intelligence-Indexer keinen expliziten Unsupported-Payloadbuilder.

Die grüne Projektion materialisiert je Relation atomare Parent-/Child-Pair-Tokens,
behält rohe Codes je Audit-Ableitung, löscht bei einem Record-Conflict sämtliche
filterbaren Relationen und trennt Katalog-, Projektions- und Deriver-Provenance. Der
aktive 204-Scope-Vertrag ergibt mit der vollständig codierten V1-Canonicalization
`spatial-projection-v1-a5ce3a4f4657`.

Fokussierte Verifikation aus den Service-Verzeichnissen:

- Data Ingestion: `103 passed, 1 skipped` (der bestehende Dev-Service-`skipif`),
  Ruff grün.
- Intelligence: `37 passed`, Ruff grün.

Es wurden keine Payload-Indizes angelegt, keine laufende Collection gelesen oder
geschrieben und kein Re-Enrichment ausgeführt.
