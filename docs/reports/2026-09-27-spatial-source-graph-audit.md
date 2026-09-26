# Spatial-, Quellen- und Graph-Audit — 2026-09-27

## Ergebnis und Prüfgrenze

PR [#119](https://github.com/Hunter5Thompson/OSINT/pull/119), geprüft auf
`5e47d8f52f2dd741151f48d16f2d576df22a85d1`, erweitert Containment korrekt von
11 auf 176 Country-Scopes. Die zwei roten CI-Tests sind lokal reproduziert und
korrigiert. **Eine fachliche Deploy-Freigabe folgt daraus nicht:** Die pauschale
Derivation-Kompatibilität akzeptiert gespeicherte Zuordnungen, die der neue
Normalizer bei identischer Quelle als Konflikt bewertet.

Basis: `main` bei `245d3d4`, PR-Worktree `fix/spatial-containment-all-countries`,
lesende Neo4j- und Qdrant-Abfragen sowie lokale Normalisierung mit beiden
unveränderten Katalogen. Live-Erhebung etwa 2026-09-26 23:31–23:36 UTC
(2026-09-27, Europe/Berlin). Der Ingestion-Container verwendet weiterhin
`spatial-v1-0180e188358c`; `odin-gdelt-backfill` läuft. Abfragen sind getrennte
Momentaufnahmen, kein gemeinsamer transaktionaler Snapshot.

Keine Datenbankmutation, kein Container-Neustart, keine Katalogaktivierung,
kein Merge oder Push. Bestehende untracked Dateien im Haupt-Checkout bleiben
unberührt. Dies ist ein gezieltes Audit der Spatial- und Feed-Verknüpfungen,
keine vollständige Prüfung sämtlicher externen Feeds oder Graph-Abfragen.

## Live-Messwerte

| Neo4j Location-Gruppe | Gesamt | Mit Country-Scope | Mit Derivation |
|---|---:|---:|---:|
| `incident_report` | 13.635 | 524 | 524 |
| `gdelt_actiongeo` | 9.959 | 6.177 | 6.151 |
| `aircraft_observation` | 4.167 | 115 | 115 |
| `country_centroid` | 131 | 0 | 0 |
| `source_country_code` | 126 | 126 | 126 |

4.165 Flugzeug-Locations besitzen noch `region`; 697 heißen `ukraine`.
Der Anteil mit Land beträgt nur rund 2,76 %. Fehlende Scope-Felder sind eine
Abdeckungslücke, aber nicht automatisch ein falscher geographischer Befund:
Meer, Grenzkonflikte, fehlende Evidenz und fehlendes Backfill sind zu trennen.

| Qdrant `source` | Punkte | Mit nichtleeren Occurrence-Tokens |
|---|---:|---:|
| `gdelt_gkg` | 1.311.495 | 16.620 |
| `firms` | 161.701 | 0 |
| `rss` | 24.152 | 0 |
| `telegram` | 4.251 | 0 |
| `ucdp` | 1.805 | 0 |
| `usgs` | 1.026 | 0 |
| `eonet` | 916 | 0 |
| `portwatch` | 850 | 0 |
| `gdacs` | 307 | 0 |
| `noaa_nhc` | 5 | 0 |

`source=gdelt`, `adsb.fi`, `ofac` und `hapi` ergaben jeweils null Punkte.
Das beweist keine allgemeine Nichtexistenz dieser Quellen: alternative
Quellenbezeichner wurden damit nicht vollständig inventarisiert.
Gezählt wurden **Punkte mit Tokens**, nicht einzelne Tokens, Revisionen oder
die Anzahl belegter Ereignisse. Die PR-Zahl 17.414 ist damit nicht direkt
vergleichbar. Auch müssen nicht alle GKG-Dokumente einen belegbaren Ereignisort
haben; 16.620/1.311.495 ist keine Qualitätsquote für den GDELT-Feed.

## Befunde und konkrete Maßnahmen

### A1 — P1: Derivation-Kompatibilität ist nicht semantisch bewiesen

Belege: `services/data-ingestion/spatial_catalog/manifest.py`,
`_extends_code_only_derivation` und `_build_scope_record`;
`graph_integrity/spatial_normalizer.py`, `normalize_location`.

Die Annahme „gleicher Crosswalk + zusätzliche Geometrie erhält alle früheren
Zuordnungen“ übersieht die Prüfung von Source-Code gegen Koordinaten.
Der Normalizer vergleicht den Punkt außerdem mit **allen** Containment-Scopes;
somit kann neue Geometrie eines Nachbarlandes sogar einen Scope beeinflussen,
dessen eigene Geometrie und Derivation unverändert bleiben.

Reproduziert mit unveränderten Katalogen:

| Eingabe | `0180…` | `a8e3…` | Alte Derivation weiter kompatibel? |
|---|---|---|---|
| ISO3 IRQ + 24.7136 / 46.6753 (Riad) | resolved IRQ | conflict IRQ/SAU | Ja |
| ISO3 RUS + 52.2297 / 21.0122 (Warschau) | resolved RUS | conflict POL/RUS | Ja |
| Nur 33.3152 / 44.3661 (Bagdad) | unresolved | resolved IRQ | Nicht anwendbar |

Ein späterer Export von 10.057 `gdelt:loc:`-Locations wurde lokal vollständig
gegen beide Kataloge normalisiert: 9.687 resolved→resolved,
106 resolved→conflict, 223 unresolved→unresolved, 41 conflict→conflict.
**62 gespeicherte, nicht-konfliktbehaftete Zuordnungen haben eine im neuen
Katalog akzeptierte Derivation, obwohl die neue Normalisierung conflict ergibt.**
Beispiele und Zähler stehen in
`2026-09-27-spatial-source-graph-audit-evidence.json` neben diesem Bericht.
Die 10.057 und die früheren 9.959 stammen aus unterschiedlichen Abfragen und
Zeitpunkten; aus ihrer Differenz wird keine Wachstumsrate abgeleitet.

Das ist ein nachgewiesener Konsistenzfehler, kein Beweis, dass Natural Earth bei
diesen Grenzpunkten sachlich richtiger ist als der Quellcode. Grobe Geometrie,
Quellfehler und Grenzpolitik können jeweils Konflikte auslösen.

Maßnahme: Kompatibilitätsvertrag vor Aktivierung klären. Entweder eine
revidierte, konservative Assignment-Revision mit den tatsächlich relevanten
Geometrie-/Resolver-Abhängigkeiten einführen, oder alte Zuordnungen vor ihrer
Freigabe unter dem neuen Katalog evidenzbezogen neu prüfen. Nur die neue
`_extends_code_only_derivation`-Sonderregel zu entfernen reicht nicht:
das RUS-Beispiel betrifft eine unveränderte eigene Derivation. Ein kurzfristiger
Cutover benötigt vollständige Re-Normalisierung und eine kontrollierte Phase,
in der ungeprüfte alte Spatial-Zuordnungen nicht als aktuell akzeptiert werden.
Das betrifft Neo4j **und** Qdrant.

Abnahme: Code-only, Code+Punkt, reine Punkte, Nachbaränderungen, Grenzpunkte
und umstrittene Gebiete testen; keine unter neuem Vertrag konfliktbehaftete
Altzuordnung darf allein wegen alter kompatibler Revision als gültig passieren.

### A2 — P1: USGS schreibt gegen die falsche Ereigniskante

`services/data-ingestion/feeds/usgs_collector.py:176` sucht
`(Document)-[:MENTIONS]->(Event)`; `pipeline.py` schreibt
`(Document)-[:DESCRIBES]->(Event)`.
Live: 906 USGS-Dokumente mit DESCRIBES zu 916 Events; weitere 108 Dokumente
ohne Event-Verknüpfung in dieser Abfrage. Null `NEAR_TEST_SITE`-Kanten.

Maßnahme: deterministischen Writer auf den aktuellen Graph-Vertrag ausrichten,
Zahl der tatsächlich geschriebenen Kanten zurückgeben und Nulltreffer sichtbar
melden. Backfill getrennt vorbereiten: Die Qdrant-Deduplizierung überspringt
bereits verarbeitete USGS-Events, daher repariert ein Codefix die Altdaten nicht.

Abnahme: Integrationstest mit realistischem Document–DESCRIBES–Event-Muster,
bekanntem Standort und Wiederholung; fehlendes Event muss als fehlende
Verknüpfung statt als erfolgreicher Write erscheinen. Nähe bleibt eine
geographische Beobachtung und darf keine Nukleartest-Bestätigung bedeuten.

### A3 — P1: FIRMS-Korrelation ist vom aktuellen GDELT-Vertrag getrennt

`feeds/correlation_job.py` filtert `source` auf `gdelt`, `ucdp`, `rss` und
erwartet skalare `latitude`/`longitude`. Der aktive Raw-Writer
`gdelt_raw/writers/qdrant_writer.py` verwendet `gdelt_gkg`,
`linked_event_ids`, `codebook_types_linked` und die Spatial-Projektion.
Live existieren 1.311.495 `gdelt_gkg`-, aber keine `gdelt`-Punkte.

Zusätzlich selektiert die Korrelation nur `possible_explosion=true`.
Der aktuelle FIRMS-Collector erzeugt dieses alte Feld nicht mehr; neue
thermische Beobachtungen laufen daher nicht durch diesen Auswahlpfad.

Maßnahme: Ereignisebene über die exakten GDELT-Event-IDs/ActionGeo anbinden;
ein bloßes Umbenennen des Filters reicht wegen Koordinaten-, Zeit- und
Kardinalitätsunterschieden nicht. Quellbeobachtung, räumlich-zeitliche Nähe und
Bestätigung eines Ereignisses getrennt modellieren. Die Entfernung allein
begründet keine `CORROBORATED_BY`-Aussage. Auswahl neuer FIRMS-Beobachtungen
ohne unbelegte Explosionsklassifikation definieren.

Abnahme: ein aktueller Raw-GDELT-Beleg korreliert mit einem passenden FIRMS-Punkt;
abweichende Zeit/Distanz, fehlende Evidenz und identische syndizierte Artikel
liefern keine zusätzliche unabhängige Bestätigung.

### A4 — P1: Ein globaler Katalog macht nicht alle Feeds räumlich abfragbar

`contracts/qdrant-spatial-writer-lanes-v1.json` unterstützt explizit nur
GDELT-GKG (`occurrence`, exakter Event-Join) und NotebookLM-Claims
(`about`, geprüfte Geo-Entität). Legacy-Feeds sind als unavailable ausgewiesen.
Die Live-Zähler bestätigen fehlende Occurrence-Tokens bei großen Feed-Beständen.
`BaseCollector._build_point` ergänzt Provenienz, aber keine Spatial-Projektion.

Maßnahme: zuerst strukturierte USGS-, FIRMS- und UCDP-Adapter, dann EONET/GDACS
und Militärflugbeobachtungen. Koordinaten, Quellpräzision, Beobachtungszeit und
stabile Quell-ID direkt übernehmen; keine erneute Ortsrekonstruktion durch das
LLM. RSS/Telegram nur aus ereignisbezogen belegten Orten, NotebookLM-`about`
nicht zu `occurrence` umdeuten. Die gemeinsame bestehende Projektion verwenden.

Abnahme: je Adapter gleiche Evidenz in Neo4j und Qdrant, idempotente IDs,
auflösbare Provenienz und klare Zähler für resolved/unresolved/conflict/
unsupported. Eine leere räumliche Suche muss fehlende Quellenabdeckung melden.

### A5 — P2: Altlasten und Reparaturpfade brauchen eigene Abnahme

Der aktuelle Batch-Writer in `graph_integrity/spatial_batch.py` korrigiert
Spatial-Felder, aber weder `name` noch `region`. Die vorgeschlagene
Flugzeugbereinigung ist daher ein zusätzlicher Schritt. Im Konfliktfall können
alte Länderfelder erhalten bleiben; `coalesce(country_iso3, 'unresolved')`
allein reicht nicht als fachliche Namensregel.

Vor einer Bereinigung `loc_key`, alte Werte **und deren Vorhandensein**, Quell-
und Katalogrevision sichern. Ein historischer Boxname lässt sich nicht
verlustfrei allein aus lat/lon garantieren: Boxversion und Auswahlreihenfolge
gehören zur ursprünglichen Ableitung. Rollback muss exakt den Before-State
wiederherstellen und zwischenzeitliche Writer-Änderungen erkennen.

Reihenfolge: Spatial-Re-Normalisierung, Konfliktprüfung, dann Namen aus
verifizierter Zuordnung ableiten und Legacy-`region` entfernen. Bei Konflikt
keine scheinbar sichere Länderbezeichnung. Scope auf
`loc_key STARTS WITH 'aircraft-observation:'` begrenzen, echte Hotspots erhalten.

Weitere Backfill-Lücken: 13.111 Incident-Locations ohne Country-Scope sowie
131 alte Länderzentroid-Locations. `graph_integrity/geo_gdelt.py` schreibt im
Legacy-Reparaturpfad OCCURRED_AT und raw lat/lon, aber keine Spatial-Felder;
darauf muss Spatial-Normalisierung folgen. Das Writer-Inventar in `report.py`
bezeichnet den Backend-Pfad noch als unsupported, obwohl `incident_store.py`
bereits `project_incident_point` verwendet: Inventar und Realität abgleichen.

Der Re-Enrichment-Plan erzeugt für diesen Übergang **165 Jobs je Lane**, also
660 bei allen vier Lanes. Jeder Job liest seine Lane vollständig und normalisiert
die Zeilen erneut. Das ist keine gemessene Laufzeit, aber ein direkt belegter
Multiplikator; Gesamtsummen sind dabei keine eindeutigen Location-Zähler.
Vor großem Betrieb nach Lane einmal scannen und nach Zielrevision dispatchen,
ohne Checkpoint-/Approval-Vertrag zu verlieren, oder Laufzeit bewusst budgetieren.

### A6 — P2: Abdeckung, Genauigkeit und Grenzpolitik getrennt behandeln

176/176 bedeutet alle **aktuellen Katalog-Scopes**, keine vollständige
Weltabdeckung. Der ISO2-Adapter erreicht 174 davon; Kosovo und Somaliland sind
eigene ODIN-Keys. Der GDELT-GEC-Adapter erreicht 172; PSE, ESH und beide
ODIN-Keys besitzen keinen Alias in diesem Index. `normalize_location` bricht
bei unbekanntem Quellcode fail-closed ab, auch wenn Koordinaten vorliegen.
Deshalb genügt zusätzliche Geometrie nicht für alle GDELT-Fälle.

Die gesperrte Admin0-Quelle ist Natural Earth `ne_110m_admin_0_countries`.
`110m` bedeutet Maßstab 1:110 Millionen, keine 110 Meter Genauigkeit. Ebenso
ist `max_error_m=0` nur die verlustfreie Darstellung gegenüber der Eingabe,
keine Zusage zur geographischen Wahrheit.

Empfehlung: separate Backend-Containment-Quelle aus Natural Earth 1:10 Millionen
evaluieren; für benötigte Verwaltungsregionen geoBoundaries-Originalgeometrien
mit expliziter Länder-/Grenzpolitik und Source-Lock. Render-LODs bleiben ein
eigener Zweck. Natural Earth beschreibt selbst de-facto-Grenzen und bietet
abweichende POV-Varianten; geoBoundaries unterscheidet Länderdateien und globale
Composite-Dateien. Ein Wechsel darf diese Perspektiven nicht still mischen.
Siehe [Natural Earth Admin0](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/),
[Grenzpolitik und Lizenz](https://www.naturalearthdata.com/about/) und
[geoBoundaries](https://www.geoboundaries.org/), am Audittag gelesen.

Abnahme: Inland, Küste, kleine Staaten, Inseln, Meer, Dateline und umstrittene
Gebiete als getrennte Referenzfälle; Abweichungen prüfen, keine künstliche
100-%-Landzuweisung. Aliase nur mit belegtem GDELT-Codesystem ergänzen.

### A7 — P2: Reload ist kein ausreichender Migrationsvertrag

Die Unterscheidung Catalog-Ref vs. Derivation ist korrekt. Der PR-Pointer
entfernt `e76a…` aus den maximal zwei served Revisionen. Zusätzlich speichert
`frontend/src/spatial/navigation.ts` die Revision im Router-/History-State
unter `odinSpatialCatalogRevision`; ein Reload ist keine zugesicherte Löschung
dieses Zustands. Die UI bietet schon die explizite Aktion
**„Aktiven Kartenstand laden“** (`spatial/react.tsx`).

Maßnahme: diese Aktion und externe gespeicherte Queries in Operator-Steps
aufnehmen; Backend/Intelligence gemeinsam auf denselben Pointer bringen.
Alte Referenzen müssen sichtbar scheitern, statt unbemerkt ihren räumlichen
Kontext zu wechseln. Siehe ergänztes Deployment-Runbook.

## Vorhandene Quellen und relevante Graph-Pfade

| Quelle/Pfad | Vorhandene Verknüpfung | Priorisierte Lücke |
|---|---|---|
| GDELT Raw | Document–MENTIONS→Event–OCCURRED_AT→Location; Document–FROM_SOURCE→Source | A1, A3; Legacy-Backfill und Qdrant-Join prüfen |
| RSS/Feed-LLM-Pipeline | Document–DESCRIBES→Event–OCCURRED_AT→Location; Document–MENTIONS→Entity | Strukturierte Geo-Evidenz statt nur dokumentweiter Länderextraktion |
| Militärflugzeuge | MilitaryAircraft–SPOTTED_AT→Location | Altname/region, globale Containment-Abdeckung, Beobachtungszeit |
| USGS | Pipeline plus beabsichtigtes Event–NEAR_TEST_SITE→NuclearTestSite | A2: falscher Beziehungstyp im MATCH |
| FIRMS-Korrelation | Document–CORROBORATED_BY→Document | A3: Quelle/Schema und Bedeutung der Kante |
| NotebookLM | Claim–EXTRACTED_FROM→Document; Claim–INVOLVES→Entity; Document–FROM_SOURCE→Source | `about` erhalten; Herkunft einer Behauptung ist keine Ereignisbestätigung |
| Incident-Promotion | Incident–OCCURRED_AT→Location | Bestehende Locations re-normalisieren; Provenienz und Konflikte erhalten |

Empfohlenes Ziel: stabile Quellbeobachtung und Dokument identifizieren,
Behauptung/Ereignis getrennt halten, Relation `about`/`occurrence` ausdrücklich
führen und Spatial-Zuordnung mit Ableitungsstand speichern. Eine kanonische
Country-/Admin-Hierarchie im Graph kann später ergänzt werden; sie ersetzt
weder die vorhandenen Scope-Keys noch die Evidenz einer einzelnen Zuordnung.
Keine pauschale Kante „Land zugewiesen“ aus einem Displaynamen ableiten.

## Reihenfolge und lokale Änderungen

1. Testfixes integrieren; A1 mit Evidenz als Deploy-Blocker behandeln.
2. Kompatibilität und Cutover für alle Writer-/Reader-Pfade entwerfen und testen.
3. GDELT-Backfill abschließen/koordiniert übergeben; Neo4j und Qdrant vor Apply
   mit gleichen Inputs prüfen. Danach separate Flugzeug-Namensbereinigung.
4. USGS-Kanten reparieren und deterministische Sensor-Adapter ergänzen.
5. FIRMS/GDELT-Korrelation fachlich und technisch auf aktuellen Vertrag bringen.
6. Feinere Geometrien und zusätzliche Länder-/Codeabdeckung als eigene Revision.

Lokaler Patch: Backend-Test liest active/served aus dem Pointer; Intelligence
prüft jede served Revision und verwendet im Route-Test keine veraltete
Katalogkonstante. Fachliche Scope-/Token-Prüfungen bleiben erhalten.
Deployment-Runbook und dieser Audit liefern die offenen Maßnahmen; A1–A6
sind damit **nicht implementiert oder produktiv repariert**.

Validierung: beide ursprünglichen Fehler vor Änderung reproduziert;
gezielte Suites danach 104 Backend- und 30 Intelligence-Tests grün;
vollständige Suites: **593 Backend-Tests und 486 Intelligence-Tests grün**
(Backend: eine bestehende Starlette-Deprecation-Warnung).
Ruff auf beiden geänderten Testdateien grün. Verwendet wurden die vorhandenen
Service-venvs des Haupt-Checkouts mit CWD und Imports aus dem PR-Worktree,
kein neu aufgebautes CI-Environment. Der GitHub-CI-Lauf bleibt ohne Push unverändert.

## Reproduktion ohne Datenbankänderung

Im PR-Worktree aus `services/data-ingestion` mit dessen Python-Abhängigkeiten:

```python
import json
from pathlib import Path
from graph_integrity.spatial_normalizer import (
    CountryCodeSystem, RawLocationIdentity, load_normalization_index,
    normalize_location,
)

root = Path('../backend/data/spatial/catalogs')
crosswalk = Path('spatial_catalog/data/country_crosswalk.json')
old = load_normalization_index(root / 'spatial-v1-0180e188358c', crosswalk_path=crosswalk)
new = load_normalization_index(root / 'spatial-v1-a8e3a4af02d0', crosswalk_path=crosswalk)
evidence = json.loads(Path(
    '../../docs/reports/2026-09-27-spatial-source-graph-audit-evidence.json'
).read_text())
for row in evidence['examples']:
    raw = RawLocationIdentity(
        country_code=row['code'], country_code_system=CountryCodeSystem(row['system']),
        latitude=row['lat'], longitude=row['lon'],
    )
    before, after = normalize_location(raw, old), normalize_location(raw, new)
    assert before.status == 'resolved'
    assert after.status == 'conflict'
    assert new.is_compatible_derivation(row['scope'], row['derivation'])
    print(row['key'], before.status, after.status, after.spatial_conflict_scope_keys)
```

Die folgenden aggregierenden Cypher-Abfragen wurden über eine READ_ACCESS-Session
mit Timeout ausgeführt; Zugangsdaten stammen aus der bestehenden Konfiguration
und werden nicht ausgegeben. Parameter: `$prefix = 'aircraft-observation:'`.

```cypher
MATCH (l:Location)
WHERE l.loc_key STARTS WITH $prefix
RETURN count(l) AS total, count(l.country_iso3) AS with_country,
       count(l.region) AS with_region,
       count(CASE WHEN l.name = 'ukraine' THEN 1 END) AS named_ukraine
```

```cypher
MATCH (l:Location)
RETURN l.geo_basis AS basis, l.type AS type, count(l) AS total,
       count(l.country_scope_key) AS with_scope,
       count(l.spatial_derivation_revision) AS with_derivation
ORDER BY total DESC LIMIT 30
```

Qdrant-Zählung: `count(exact=True)` mit `source == <Tabellenwert>`;
zweite Zählung mit zusätzlichem `IsEmptyCondition` auf
`spatial_occurrence_scope_revision_tokens`; Differenz ergibt Punkte mit Tokens.
Es wurden keine Embeddings oder vollständigen Dokumenttexte abgefragt.
