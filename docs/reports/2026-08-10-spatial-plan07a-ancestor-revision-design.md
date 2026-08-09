# Spatial Plan 07A — Ancestor-/Revision-Design-Gate

**Datum:** 2026-08-10

**Scope:** Qdrant-Payload- und Filterrepräsentation; keine Live-Mutation

## Befund und RED

Der aktive Katalog weist `country:UKR` die Derivationsrevision
`spatial-derive-v1-d30efa07e141` und dessen Child
`admin1:iso3166-2:UA-14` die Revision
`spatial-derive-v1-4d1de888e0c7` zu. Der Plan-06A-Normalizer materialisiert beide
Scope-Keys, sein recordweiter Scalar trägt jedoch nur die Revision des terminalen
Admin-1-Scopes. Der bisherige Spec-09-Country-Filter konnte diesen gültigen Point
daher nicht finden.

Der erste Contract-Test wurde vor der Implementation ausgeführt und scheiterte mit:

```text
FAILED tests/test_spatial.py::test_admin1_point_matches_child_and_parent_only_with_correlated_revision
ModuleNotFoundError: No module named 'spatial'
```

Der persistente Regressionstest enthält drei Punkte: ein korrektes UA-14-Assignment,
einen Poison-Point mit vertauschten Country-/Admin1-Revisionen und einen Point mit
inkompatiblen Revisionen. Nur der korrekte Point darf über Parent und Child gefunden
werden.

## Reviewte Alternativen

1. **Nested Assignments:** getrennte About-/Occurrence-Arrays aus Objekten mit
   `scope_key` und `derivation_revision`. Lesbar und erweiterbar, aber vier
   Leaf-Indizes und je zwei korrelierte Filterbedingungen. Qdrant unterstützt Nested
   Conditions seit Version 1.2.
2. **Compound Keyword:** ein atomarer Relation-/Scope-/Revision-String. Kleinster
   Filter und nur ein Index, aber die Relation wäre am Payload-Seam nur im Encoding
   sichtbar.
3. **Katalogvergebene Integer-ID:** bijektive Registry je Scope-/Revisionspaar und
   getrennte Relationsarrays. Kleine Payloads, aber neue append-only Vergabe-,
   Stabilitäts- und Auditkomplexität im Katalog.

## Entscheidung

Gewählt wurde ein Hybrid mit zwei relation-spezifischen Keyword-Arrays und atomarem
Pair-Token:

```text
spatial_about_scope_revision_tokens[]
spatial_occurrence_scope_revision_tokens[]
sr1|<ScopeKey>|<DerivationRevision>
```

Das Interface hält Relationen getrennt, benötigt nur zwei Pair-Indizes und kann jede
Compatibility-Menge als ein Qdrant-`MatchAny` kompilieren. `|` ist weder in der
ScopeKey- noch in der Derivationsrevisionsgrammatik erlaubt. Das Encoding ist damit
reversibel und injektiv, ohne Hash-Collision. Die Maximallänge beträgt 229 ASCII-Byte.

Qdrant dokumentiert sowohl die Nested-Alternative als auch flache exakte Keywords
für kategoriale Paarwerte:

- <https://qdrant.tech/documentation/search/filtering/>
- <https://qdrant.tech/documentation/manage-data/indexing/>

## Revisionssemantik

Der Qdrant-Scalar `spatial_derivation_revision` entfällt. Die fachliche Revision
steht ausschließlich im Pair-Token und im nicht indexierten Audit-Feld
`spatial_derivations`. `spatial_catalog_revision` bleibt Audit-Provenance.

Neu ist `spatial_projection_revision`: ein SHA-256-basierter Fingerprint aus
Pair-Token-Version, Deriver-Version, About-Gate-Policy und der sortierten vollständigen
Scope→Derivationsrevisionsmenge. Er steuert Checkpointing und Idempotenz, wird aber nie
gegen einen Request-Token gefiltert. Ein reiner Catalog-Carry-forward verändert ihn
nicht und löst keinen Corpus-Rewrite aus.

Work Order 2 konkretisierte die zuvor noch nicht codierte Canonicalization: sortiertes
kompaktes JSON, Gate-Revision
`about-gate-v1-unique-reviewed-crosswalk-confidence-gte-0.80` und vollständige
sortierte Scope-/Revisionspaare. Für den aktiven 204-Scope-Katalog ergibt das
`spatial-projection-v1-a5ce3a4f4657`.

Der eingecheckte sprach-/service-neutrale Vertrag einschließlich Indexvektor und
UA-14-Beispiel ist `contracts/qdrant-spatial-payload-v1.json`.

## Gate

Work Order 0 ist grün; Work Order 1 darf beginnen. Die bestehende Live-Collection
blieb unverändert. Der verwandte Neo4j-Parent-Sachverhalt bleibt vor einer
Country-Promotion tiefer aufgelöster Locations separat promotionsblockierend.
