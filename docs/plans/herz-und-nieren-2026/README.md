# Fixplan: Herz und Nieren 2026 Alpha

**Status: aktiv; HN-S01 und HN-S02 abgeschlossen (PR #128, Merge `732fadc`), HN-S03 gemergt (PR #129, Merge `58843a7`, CI erfolgreich), HN-I01 gemergt (PR #131, `a45a13c`), HN-I02 gemergt (PR #132, `a3fc29c`); HN-I04 gemergt (PR #133, `1eb5fdb`); B01 I05/I06/I03 gemergt (PR #134, Merge `77a98ad`). B02 D04/D05/D11 gemergt (PR #135, Merge `6742481`); B03 D08/A01/A05/A06 gemergt (PR #136, Merge `ef0316c`); B04 D03/A04 gemergt (PR #137, Merge `1359d14`); B05 D01/D02/D10 fachlich abgenommen, Merge/Deployment offen.** Baseline: `374c5cc460ebea44ad27f0ddfe09a11fd2d57e83` (2026-09-27). [Senior-Bewertung mit vollständiger Finding-Matrix](../../reports/Herz_und_Nieren_2026_Alpha_Review.md).

## Ausführung mit Senior und GPT-6-Luna

Die Nutzervorgabe vom 2026-09-27 ersetzt „ein PR pro Ticket“: **ein PR pro Themenbündel**, intern sequenzielle Ticket-Unterläufe. Senior koordiniert und reviewt, GPT-6-Luna implementiert. Pro Unterlauf die jeweilige Ticketsektion, diese gemeinsame Anleitung, `AGENTS.md` und die im Ticket genannten Dateien lesen. Der ganze Prüfbericht und das ganze Repository sind kein notwendiger Promptkontext. Relative Codepfade in Tickets beziehen sich auf den jeweils genannten Service. Direkt betroffene bestehende Tests und neue Regressionstests sind immer im erlaubten Scope. Importierte Hilfsdateien bei Bedarf gezielt lesen; zusätzliche Schreibpfade erst im Ergebnis begründen, keine fremden Module nebenbei reparieren.

1. Baseline/Dirty-State prüfen. Existierende Änderungen erhalten. Auf inzwischen behobene Findings zuerst den Regressionstest anwenden, keinen Fix erzwingen.
2. Ticket-ID im Task-Registry `TASKS.md` registrieren/verknüpfen, sobald die Umsetzung beginnt. HN-Paket-IDs sind lokale Plan-IDs, keine erfundenen offiziellen TASK-Nummern.
3. Bestehende benachbarte Tests als Baseline laufen lassen. Regression zuerst schreiben und **am richtigen Fehler** rot sehen. Import-/Setupfehler sind kein RED-Beweis.
4. Minimal implementieren, gezielte Tests grün; erst danach aufräumen. Keine erfundenen Daten, kein `any`, kein LLM-Cypher auf dem Schreibpfad, DB-Parameter binden.
5. Pro Ticket die angegebenen Regressionstests; am Ende jedes Bündels die vollständigen Checks aller berührten Services einmal auf dem gemeinsamen Stand. Unveränderte Services nicht erneut testen. Zwischen Unterläufen kein eigener PR und keine Mergepause.
6. Ergebnis maximal 15 Zeilen: Ticket, Baseline, geänderte Dateien, RED-/GREEN-Befehl mit Ergebnis, offene Grenzen, Anschlussvertrag. Kein „PASS“ ohne ausgeführten Check. Fehlende DB/Browser-Abnahme ausdrücklich als offen ausweisen.

**Stopregel für das kleine Modell:** Nach zwei erfolglosen Reparaturversuchen, bei unklarer API-/Datenmigration, notwendigem Scope-Ausbau oder neuer Sicherheitsentscheidung mit minimalem Repro eskalieren. Keine wiederholte Vollrepo-Analyse. Als Senior-markierte Pakete benötigen fachliche Abnahme; das ist eine Empfehlung dieses Plans, keine jetzt angeforderte Benutzerfreigabe.

Der bestehende Umsetzungsauftrag deckt Implementierung, scoped Commit/Push und Bündel-PRs ab. Aus diesem Plan keine zusätzliche Live-Datenmigration, Dienste-Neustarts, Downloads oder Deployment ableiten. Für Integrationstests ausschließlich isolierte Testdaten/Instanzen verwenden; niemals Mutationsproben gegen die produktive Neo4j.

## Bündelplan und Reihenfolge

**Bündelbasis: 36 Implementierungstickets → 13 Themen-PRs.** B01 mit drei Tickets
ist gemergt; B02 mit drei weiteren Tickets ist ebenfalls gemergt.
B03 mit vier weiteren Tickets ist gemergt (PR #136, `ef0316c`).
Nach B03 verblieben 26 Fix-Tickets in zehn Bündeln; B04 (D03, A04) ist gemergt; B05 (D01, D02, D10) ist fachlich abgenommen, Merge offen. Die Einzel-IDs,
Scopes und Abnahmekriterien bleiben erhalten. A02 ist in D07 enthalten und wird nicht
nochmals gezählt. Die bereits gemergten S01/S02/S03/I01/I02/I04 bleiben abgeschlossen.
Diese Bündelreihenfolge ersetzt die frühere PR-Reihenfolge nach Wellen.

| Reihenfolge / Bündel | Thema | Ticket-Unterläufe | Gemeinsame Abnahme |
|---|---|---|---|
| ~~B01~~ (gemergt, PR #134) | Incident-Recovery und Zeitwerte | ~~I05~~ → ~~I06~~, ~~I03~~ | Rehydration, Health/Inspector, deterministische Zeitwerte, Telegram-Eviction; Backend-Gesamtchecks |
| ~~B02~~ (gemergt, PR #135) | Backend-Feeds und Cache-Recovery | ~~D04~~, ~~D05~~, ~~D11~~ | Fehlerhafte Einzelzeilen, Cache-Recovery und Feed-Freshness; Backend-Gesamtchecks |
| ~~B03~~ (gemergt, PR #136) | Ingestion-Parser und Quellidentität | ~~D08~~, ~~A01~~, ~~A05~~, ~~A06~~ | Je Quelle eigener RED/GREEN-Unterlauf; Collector-/Pipeline-Verträge und Ingestion-Gesamtchecks |
| ~~B04~~ (gemergt, PR #137) | Graph-Auswahl und Claim-Kanten | ~~D03~~, ~~A04~~ | Isolierte echte Neo4j-Fixtures für Filter und typgebundene Kanten; Backend/Ingestion |
| ~~B05~~ (fachlich abgenommen, Merge offen) | Schiffs- und Flugmesswerte | ~~D01~~ → ~~D02~~, ~~D10~~ | Producer→API→Anzeige, unbekannte Werte und Rollen; Backend/Ingestion/Frontend samt Browser-Smoke |
| B06 | Hotspot-Daten und Abdeckung | A03, D06; X01/X02-Entscheidungsvorlagen | Keine Absenkung bei Ausfall, saubere Texte; bestehende Policy erhalten, Abdeckungsgrenzen dokumentieren |
| B07 | Kanonische Identitäten | A07, A08 | Vor Codeänderungen Legacy-ID-/Key-Konzept prüfen; Hash-/Key-Parität, keine Live-Reingestion oder Migration |
| B08 | Agentensteuerung | L01, L02, L03 | Intent, Assessment und tatsächliche Toolstarts gemeinsam prüfen; Intelligence-Gesamtchecks |
| B09 | RAG und Schema-Bereitschaft | S04, L04, L05 | Schema erst nach Erfolg, Poison-Hit-Isolation und Chunkergrenzen; Vision/Intelligence-Gesamtchecks |
| B10 | Berichte und Admin-Zugriff | L06, D09 | Berichtparser und normalisierte Admin-Fallbacks; Backend-Gesamtchecks |
| B11 | Globe-Geometrie und Interaktion | U01, U02, U03, U04 | Datumsgrenze, Pol, Zeitraster und Picking; Frontend-Gesamtchecks und Browser-Smoke |
| B12 | Asynchrone UI-Zustände | U06, U07, U08; X03-Entscheidungsvorlage | Alte Antworten, Eventdetailwechsel und SSE-Resets; Backend/Frontend-Verträge und Browser-Smoke |
| B13 | Satellitenparser und Cesium-Uhr | D07 (einschließlich A02) → U05 | Gemeinsame Parserfixtures, Propagation/Lifecycle, Browser-Smoke; Backend/Ingestion/Frontend |

**Nutzervorgabe 06.10.2026:** Nach B05 folgt zunächst die Betriebsprüfung von Datenfrische, Analysequalität, Browser-Verhalten und tatsächlich deploytem Code. B06 bleibt der nächste offene Codeblock, wird aber nicht automatisch begonnen. [B05-Abnahme](../../reviews/2026-10-06-hn-b05-acceptance.md), [Live-Befunde](../../reports/2026-10-06-odin-live-status.md).

### Arbeits- und Mergevertrag

- Ein frischer isolierter Branch/Worktree von aktuellem `origin/main` pro Bündel.
  Tickets innerhalb des Bündels sequenziell und mit eigenen fachlichen RED/GREEN-
  Nachweisen bearbeiten; keine Tests oder Scopes wegen der Bündelung streichen.
- Zusammengehörige Änderungen gemeinsam reviewen. Senior prüft den tatsächlichen
  Gesamt-Head unabhängig und schickt Findings direkt an Luna. PR-Beschreibung und
  TASKS führen jede enthaltene Ticket-ID mit Ergebnis und offenen Grenzen auf.
- Ein PR, ein vollständiger Service-Abschlusslauf und eine Mergepause pro Bündel.
  Erst nach Merge das nächste Codebündel beginnen. Die frühere Einzel-PR-Regel ist
  aufgehoben; die fehlende pauschale Merge-Freigabe bleibt unverändert.
- Binnenabhängigkeiten sind Reihenfolge im selben PR: I04 ist gemergt, dann
  I05 → I06; D01 vor D02; D07 und X04-Formatentscheidung vor U05. S01 als
  Voraussetzung für L01 und S02 → S03 sind bereits erfüllt.
- Ein blockiertes Produktdesign hält unabhängige Fixes nicht auf. Bei unerwartetem
  Migrationsbedarf oder nicht mehr sinnvoll gemeinsam prüfbarem Umfang begründet
  Senior einen Split; keine Rückkehr zu Einzel-PRs allein wegen der Ticketanzahl.
- Ticketstatus erst nach bestandenem Einzelkriterium abhaken, Bündel erst nach
  Gesamtprüfung abnehmen; Review, Merge, Deployment und historische Datenkorrektur
  bleiben getrennte Aussagen.

### Designspur und ehrliche Zählgrenze

X01–X04 bleiben vier **offene Designaufträge**, keine implizite Autorisierung neuer
Produktpolitik. X01/X02 werden in B06 und X03 in B12 mitgeführt; ihre unabhängigen
Fixes können vorher abgeschlossen werden. X04 beginnt **früh neben B01** als
read-only Designarbeit und wird vor B13 entschieden, nicht erst am Ende entdeckt.
Die [frühe X04-Entscheidungsvorlage](X04-design-notes.md) liegt vor; Formatfreigabe
und Umsetzung bleiben offen.
Die Designnotizen werden in die ohnehin anstehenden Bündel-PRs aufgenommen.

Die 13 PRs decken die 36 schon konkretisierten Fix-Tickets ab. Eine nach X04
freigegebene GP-JSON/OMM-Umstellung mit X04a–d ist darin **nicht als umgesetzt
gezählt**: zunächst Modell, Cacheversion, Propagator und kompatible Rolloutfolge
festlegen. Danach möglichst in B13 integrieren, sofern unabhängig deploybare
Kompatibilitätsstufen und Reviewumfang das erlauben; sonst einen begründeten
Folge-PR planen. Dasselbe gilt für zusätzliche Produktänderungen aus X01–X03.
D07 allein schließt X04 nicht. Daher Ziel **13 Fix-PRs**, keine garantierte Obergrenze
für noch unentschiedene Erweiterungen.

R01 bleibt ein separates historisches Datenpaket: nach dem jeweiligen Codefix
read-only Inventar/Dry-run, keine Livekorrektur aus dieser Bündelung ableiten.

## Kontextpakete

| Datei | Inhalt |
|---|---|
| [01-security.md](01-security.md) | S01–S04: Cypher, Vision, Schema-Gate |
| [02-incidents.md](02-incidents.md) | I01–I06: FIRMS, Retry, Telegram, atomare Mutation, Rehydration, Zeiten |
| [03-data.md](03-data.md) | D01–D11: Feeds, Cache, Graphfilter, Zuordnung, Health |
| [04-intelligence.md](04-intelligence.md) | L01–L06: Intents, Assessments, Toolbudget, RAG, Chunker, Berichtparser |
| [05-ui.md](05-ui.md) | U01–U08: Geometrie, Zeit, Picks, Lifecycle, Rennen |
| [06-followups.md](06-followups.md) | A01–A08, X01–X04 und historische Datenreparatur |

Jede `## ID — ...`-Sektion bleibt ein kopierbarer Unterauftrag innerhalb eines Bündels. Beispiel: nur I01 extrahieren:

```bash
sed -n '/^## I01 /,/^## I02 /p' docs/plans/herz-und-nieren-2026/02-incidents.md
```

## Gemeinsame Verträge

- **Messdaten:** fehlend/ungültig ≠ 0; `NaN`/Infinity nie als JSON-Nutzwert. Position erhalten, wenn nur optionale Attribute fehlen. Cachewerte nach denselben Regeln lesen wie Livewerte; Altcache darf Fehler nicht wieder einführen.
- **Zeit:** naive historische ISO-Zeit wird explizit als UTC behandelt; bereits zonierte Zeit konvertieren. Ungültige Pflichtzeit bei Reads macht den Datensatz ungültig; kein `now()`/1970. Optionale Zeit bleibt `null`. Epoch-Einheit pro Quelle explizit, keine globale 10-/13-Stellen-Heuristik.
- **Cache:** dokumentiert gültiges `[]` ist ein leerer Snapshot, kein kaputter Cache. Ein ungültiger Root oder ausschließlich ungültige Zeilen ist Miss. Gemischte Liste liefert gültige Zeilen und ein Diagnoseereignis. Transport-/DB-Ausfall niemals als erfolgreich leere Daten tarnen.
- **Persistenz:** lokale Parserkorrekturen reparieren keine historischen Datensätze. Kein automatisches Backfill oder globales Cache-Löschen. Identitätsänderungen haben ein eigenes Migrationskonzept.
- **Fehlerisolation:** einzelne Quelldatenfehler isolieren und aggregiert protokollieren. Infrastrukturfehler als Infrastrukturfehler melden; nicht mit Broad-Except zu Erfolg machen.
- **UI:** echte unbekannte Werte neutral anzeigen; keine falsche Bewegungsrichtung/Rolle. Cesium imperativ, Listener/Timer entfernen, keine React-Updates pro Objekt/Tick. Spatial-Revisionsschutz und Typed-Evidence-Provenienz erhalten.

## Verifikation

Kommandos immer aus dem Serviceverzeichnis. Vorhandene Umgebung pro betroffenem Service prüfen: Python mit **uv 0.10.0**, `uv sync --locked --all-extras`; Frontend **Node 22**, `npm ci`. Vorhandene korrekte Umgebung nicht je Ticket neu installieren. Große Caches/Artefakte nach `/data`; vor Multi-GB-Downloads freie Kapazität prüfen.

Gezielter Pythonlauf: `uv run pytest <Testdatei> -q`; Frontend: `npm test -- <Testdatei>`. Die Ticket-Dateinamen sind vorhandene Testanker oder explizit als „neu“ bezeichnet; neue Tests am bestehenden Namensschema ausrichten.

| Service | Bündelabschluss |
|---|---|
| Backend | `uv run pytest`; `uv run ruff check app/`; `uv run mypy app/` |
| Intelligence | `uv run pytest` |
| Data-Ingestion | `uv run pytest` |
| Vision-Enrichment | `uv run pytest` |
| Frontend | `npm run lint`; `npm run type-check`; `npm test`; `npm run build` |

Zusätzlich `git diff --check` und scoped Diff-Review. Echte Neo4j-Tests für D03/I04/A04; Sicherheits-Negativtests für S01–S04 ohne Kontakt zu internen Zielsystemen. Browser-Smoke mit repräsentativen Screenshots für U01–U08 und D01/D02/D10: Datumsgrenze, Pol, Scrubber, überlagerte Picks, Layer an/aus, WorldView→Briefing→WorldView. Keine Erfolgsaussage allein aus Build oder Mocktests.

## Direkt verwendbarer Startprompt

> Bearbeite Bündel `<Bxx>` gemäß obiger Tabelle. Implementiere nacheinander dessen Ticket-Unterläufe, beginnend mit `<ID>` aus `<Datei>`. Lies diesen README-Vertrag, die aktuelle Ticketsektion, AGENTS.md und nur die genannten Code-/Testanker. Prüfe den aktuellen Stand; vorhandene Änderungen erhalten. Arbeite TDD: fachlich roter Regressionstest, minimale Korrektur, gezielte grüne Tests. Beachte Scope, Abhängigkeiten und Nichtziele. Keine Live-Migration und kein Deployment. Commit/Push/PR gemäß dem bestehenden Arbeitsauftrag durch Senior koordinieren; kein eigener PR je Unterlauf und kein eigenständiger Merge. Bei den Stopbedingungen liefere einen kleinen reproduzierbaren Blocker statt zu raten. Berichte knapp mit ausgeführten Befehlen und Ergebnissen. Starte jetzt mit dem Baseline- und Regressionstest.
