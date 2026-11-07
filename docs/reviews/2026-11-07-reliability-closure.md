# Abschluss der fünf Stabilisierungspakete — 07.11.2026

Die fünf am 06.11.2026 freigegebenen Pakete sind im vereinbarten Umfang umgesetzt,
integriert und technisch abgenommen. Die fachliche Annahme betrifft den vorgelegten
Rechercheentwurf. Die native Dauerprüfung gilt für den ausdrücklich dokumentierten
Chromium/Vulkan-Modus auf dieser Workstation. Externe Faktengültigkeit, automatische
Prognosen und beliebige Grafik-/Treiberkonfigurationen sind damit nicht freigegeben.

Der Abschluss dauerte über Mitternacht hinaus. Die fehlgeschlagenen Diagnoseläufe
und ein korrigierter Fehler in der Testvorbereitung bleiben vollständig erhalten.
Plan: [fünf Pakete](../plans/2026-11-06-reliability-closure.md).
Lokale Nachweise: `/data/odin-reliability-20261106`.

## Ergebnis je Paket

| Paket | Umsetzung und Abnahme | Integration |
|---|---|---|
| P1 Source/Betriebsstand | Drei Lintfehler korrigiert; aktuelle Notebook-/Recherchearbeit integriert; Registry trennt Source und aktive Revisionen | [PR 154](https://github.com/Hunter5Thompson/OSINT/pull/154), 21 erfolgreiche CI-Prüfungen |
| P2 Ingestion/Feeds | Pending-Slice `20260827091500` erfolgreich aufgearbeitet; anschließender neuer Slice nachgewiesen; OFAC-Verträge repariert; Einzelfeed-Ausfälle sichtbar | [PR 155](https://github.com/Hunter5Thompson/OSINT/pull/155), 17 erfolgreiche CI-Prüfungen; Ingestion `b56f2cd` aktiv |
| P3 Dossierintegrität | Atomare Teilupdates; kein Lost Update disjunkter Felder und keine Wiederanlage gelöschter Berichte; Leerpatch ohne Änderung; neue Entwürfe ohne erfundene Angaben | [PR 156](https://github.com/Hunter5Thompson/OSINT/pull/156), 21 erfolgreiche CI-Prüfungen; reale DB- und Live-Prüfungen bestanden |
| P4 Recherchequalität | Eingefrorene Entwicklungs-/Holdout-Fälle, drei echte Anwendungsfälle, Speicherung/Reload und Abbruch geprüft; Nutzer nimmt vorgelegten Bericht vorläufig an | [PR 157](https://github.com/Hunter5Thompson/OSINT/pull/157), 21 erfolgreiche CI-Prüfungen; Intelligence `badfbf7` aktiv |
| P5 Betriebswahrheit/Dauerbetrieb | Redis-Recovery, Readiness, ehrliche RAG-Antworten, aggregierte Histogramme und native 60-Minuten-Prüfung bestanden; gezielter Rollout und Nachprüfung erfolgreich | [PR 158](https://github.com/Hunter5Thompson/OSINT/pull/158), 21 erfolgreiche CI-Prüfungen; Backend/Frontend `70a175a` aktiv |

## Prüfbelege

- P2: 1.832 Ingestion- und 1.213 Backend-Tests. Im tatsächlichen neuen Container
  wurden 19.563 OFAC-SDN- und 486 konsolidierte Einträge abgerufen und geparst.
  Das ist kein behaupteter vollständiger Embedding-Reingest.
- Der abschließende Feedstatus enthält 35 verfügbare, drei nicht verfügbare und
  20 nicht konfigurierte Feeds. UN News antwortet mit 404, zwei EU-Parlamentsfeeds
  mit 403. Für HAPI fehlt der konfigurierte Identifier. Erfolgreiche Nachbarfeeds
  können diese Zustände nicht mehr verdecken.
- P3: 18 echte Metadaten-/Konkurrenzfälle in isoliertem Neo4j; anschließend echte
  Anlage, parallele Feldänderungen, Reload, Leerpatch, null/0 und Update nach
  Löschen gegen die Anwendung bestanden. Nur ein eigener synthetischer Testbericht
  wurde dabei gelöscht.
- P4: 40 Entwicklungs- und 40 zurückgehaltene Quellenfälle, jeweils 20 korrekte
  und 20 veränderte Zusammenfassungen. Je Split null falsche Freigaben und 19/20
  korrekte Zusammenfassungen angenommen. Die jeweils eine falsche Enthaltung
  bleibt dokumentiert. Quellenvergleich nach einer Entwicklungskorrektur 8/8
  Entwicklungs- und anschließend 8/8 unveränderte Holdout-Fälle; 994 Service-Tests.
- Echte Anwendung: aktuelle Recherche rund 82,7 s, historische Recherche 82,7 s,
  Nichttreffer 22,5 s. Reservierte/providerberichtete Suchcredits: aktuell 4/2,
  Nichttreffer 4/4. Die Archivfrage reservierte null Credits und stellte keine
  externe Suchanfrage; eine Provider-Verbrauchsmeldung liegt dafür nicht vor.
  Drei bezeichnete REVIEW-Dossiers enthalten gespeicherte und erneut geladene
  Ergebnisse. Chatantworten wurden ausdrücklich über die Report-API in die eigenen
  leeren Testentwürfe übernommen; keine automatische Überschreibung redaktioneller
  Texte und kein behaupteter UI-Knopf zum Übernehmen einer Antwort.
- Abbruch: UI reagiert nach rund 83 ms; nach 292 s keine verspätete Assistentenantwort.
  Providerverbrauch des abgebrochenen Aufrufs unbekannt; keine behaupteten Eurokosten.
- P5: 1.221 Backend- und 967 Frontend-Tests sowie drei Launcher-Vertragstests.
  Echte isolierte Redis-Prüfung besteht fehlgeschlagenen Start, spätere Unterbrechung
  und Wiederanlauf. Readiness trennt notwendige Neo4j-/Qdrant-Verfügbarkeit von Redis.
- Zwölf Histogramm-Vergleiche mit je 20.000 synthetischen Ereignissen stimmen mit
  der vorherigen Python-Auswertung überein. Insgesamt 135.510 Einzelzeilen werden
  zu 43 Ergebniszeilen, etwa 11,8 MB zu 162 kB. Synthetische Median-Abfragezeit
  169 auf 38 ms. Kein Ereignis-LIMIT; keine Produktions-SLA. Nutzlastgröße hängt
  weiterhin von Kategorie-/Schweregradkombinationen ab, die DB liest die Treffer.

## Native Abnahme und Testkorrektur

Zwei OpenGL-Diagnoseläufe scheiterten nach etwa 26 beziehungsweise 15,5 Minuten
mit Kontextverlust und NVIDIA Xid 31/69. Sie verwendeten einen lokalen Build ohne
aktivierten Spatial-Pfad. Ein erster Vulkan-Diagnoselauf blieb stabil, wurde nach
rund 49 Minuten jedoch abgebrochen, als der Artefaktvergleich die fehlende lokale
Buildvariable `VITE_SPATIAL_SCOPE_ENABLED=true` zeigte. Diese Läufe sind keine
Release-Abnahme und beweisen keinen Fehler des Spatial-aktivierten Releases unter
OpenGL. Aus einer Xid-Meldung allein folgt auch keine eindeutige Ursache; siehe
[NVIDIA-Dokumentation](https://docs.nvidia.com/deploy/xid-errors/introduction.html).

Für die endgültige Abnahme wurden sämtliche 411 statischen Dateien direkt aus dem
unveränderlichen Frontend-Image kopiert und unabhängig dagegen gehasht. Die vier
nativen Kurztests und der vollständige Stundenlauf wurden darauf neu ausgeführt.
Der aktivierte Spatial-Pfad ist über tatsächliche Katalogabrufe nachgewiesen.
Eine zusätzliche Regression weist den deaktivierten Build nun ausdrücklich zurück:
Vor der Korrektur akzeptierte der Test ihn, danach wurde er abgewiesen; das echte
Release-Artefakt besteht. Diese Guard-Regression lief getrennt mit SwiftShader und
ist selbst kein nativer Leistungsbeleg.

Qualifizierte Konfiguration: Chromium 156.0.8078.4, ANGLE/Vulkan 1.4.329, RTX 5090,
Treiber 595.84. Dieselben Browserflags stehen im separaten Operator-Launcher.
Kein Treiberwechsel, GPU-Reset oder Wechsel eines Modellservers war erforderlich.
Die vier Kurztests erreichten 59,84–60,01 tatsächliche FPS und 17,1 ms p95 Frameabstand.
Der vollständige Release-Lauf dauerte 60,06 Minuten mit 142 Messungen, ohne
Renderfehler, unerwarteten Kontextverlust oder Kernel-Xid.

| Messgröße | Median Minute 10–15 | Median Minute 55–60 | Änderung | Grenze |
|---|---:|---:|---:|---:|
| Browser-RSS | 211,4 MiB | 204,5 MiB | −6,9 MiB | <32 MiB |
| GPU-Prozess-RSS | 407,0 MiB | 411,6 MiB | +4,7 MiB | <64 MiB |
| Renderer-RSS | 849,8 MiB | 871,2 MiB | +21,4 MiB | <128 MiB |

Browser-Trend nach Minute 10: −0,209 MiB/min bei Grenze <0,5. JS-Heap-Zunahme der
festgelegten Vergleichsfenster rund 1,96 MiB bei Grenze <5 MiB; DOM-Zunahme null
bei Grenze <50. Die Kriterien wurden nicht gelockert. GPU-Prozess-RSS ist kein
Nachweis über den gesamten gemeinsam genutzten VRAM. Der Test verwendet synthetische
Flugdaten und mitgelieferte Karten; entfernte Terrain-Dienste, allgemeine
Treiberstabilität und menschliche visuelle Abnahme bleiben separate Fragen.

Startbefehl und Betrieb: [Runtime/Native-Browser](../operations/runtime-readiness-and-bounds.md).
OpenGL besitzt hier keine vollständige Release-Qualifikation; der nachgewiesene
native Betriebsmodus ist der dokumentierte Vulkan-Launcher.

## Ausgelieferter Stand und Nachprüfung

- Backend/Frontend: `70a175af3e98ffe13646d9f45ddaae7a559c5621`.
- Intelligence: `badfbf7d9cf261d8aeb249b50157638cfc2d9fa8`.
- Spark-Ingestion: `b56f2cda1878673fe1100b5f3dd1e2421cf43352`.
- P5 integriert mit Merge `dfef99364b3f21f6c9666cfeb47181659d48fb07`.

Nach dem gezielten Austausch von Backend/Frontend: Readiness vollständig `ready`,
RAG-Statistik und Quellzählungen verfügbar, manueller Import HTTP 501 ohne Job.
Live-Histogramme bestanden Summen-/Kategorie-/Schweregradkonsistenz; die globale
2-Stunden-Abfrage lieferte 545 Ereignisse in sechs belegten Buckets in 183 ms,
die Antimeridian-Abfrage null Treffer in 19 ms. Das sind Momentaufnahmen.
Ausgelieferte JS-/Engine-/Build-Metadaten stimmen mit dem qualifizierten Image
überein; der sichtbare Vulkan-Launcher besteht auch nach dem Rollout.
Vorherige Images und identische effektive Einstellungen/Mounts sind als Rückweg
gepinnt. Umgebungstragende Dateien liegen ausschließlich im geschützten `private/`.

27 übrige Containeridentitäten blieben gleich. Der fremde dirty Home-Checkout
auf `813594a` wurde bewahrt. Das Originalarchiv mit 84 Quellen / 2.351 Passagen
behält SHA-256 `8abdb28e6851dc8534acf80fda645ad580559a1a283428798a24b6476c7ad2f0`.
Eigene isolierte Testdatenbanken wurden gezielt entfernt, fremde Daten nicht bereinigt.

## Fachliche Annahme und verbleibender Umfang

Nutzerantwort: „Also der Bericht passt erstmal hab nichts auszusetzen“.
Dies ist als vorläufige Annahme des vorgelegten Rechercheentwurfs dokumentiert,
nicht als unabhängige Einzelprüfung jedes Tests oder externe Faktenprüfung.
Die drei RSS-Anbieterfehler und die HAPI-Konfiguration bleiben sichtbar; zuverlässige
Prognosen und vollständige Quellenabdeckung sind weiterhin nicht qualifiziert.
Nächste sinnvolle Arbeit sind diese konkreten Anbieter-/Konfigurationsfragen und
eine größere unabhängige fachliche Stichprobe unter realer Nutzung, bevor neue
umfangreiche Produktfunktionen begonnen werden.
