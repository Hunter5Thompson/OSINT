# Fixplan: Herz und Nieren 2026 Alpha

**Status: aktiv; HN-S01 und HN-S02 abgeschlossen (PR #128, Merge `732fadc`), HN-S03 implementiert (Review offen), alle übrigen Pakete offen.** Baseline: `374c5cc460ebea44ad27f0ddfe09a11fd2d57e83` (2026-09-27). [Senior-Bewertung mit vollständiger Finding-Matrix](../../reports/Herz_und_Nieren_2026_Alpha_Review.md).

## Ausführung für ein kleineres LLM

Pro Lauf genau **eine Ticketsektion**, diese gemeinsame Anleitung, `AGENTS.md` und die im Ticket genannten Dateien lesen. Der ganze Prüfbericht und das ganze Repository sind kein notwendiger Promptkontext. Relative Codepfade in Tickets beziehen sich auf den jeweils genannten Service. Direkt betroffene bestehende Tests und neue Regressionstests sind immer im erlaubten Scope. Importierte Hilfsdateien bei Bedarf gezielt lesen; zusätzliche Schreibpfade erst im Ergebnis begründen, keine fremden Module nebenbei reparieren.

1. Baseline/Dirty-State prüfen. Existierende Änderungen erhalten. Auf inzwischen behobene Findings zuerst den Regressionstest anwenden, keinen Fix erzwingen.
2. Ticket-ID im Task-Registry `TASKS.md` registrieren/verknüpfen, sobald die Umsetzung beginnt. HN-Paket-IDs sind lokale Plan-IDs, keine erfundenen offiziellen TASK-Nummern.
3. Bestehende benachbarte Tests als Baseline laufen lassen. Regression zuerst schreiben und **am richtigen Fehler** rot sehen. Import-/Setupfehler sind kein RED-Beweis.
4. Minimal implementieren, gezielte Tests grün; erst danach aufräumen. Keine erfundenen Daten, kein `any`, kein LLM-Cypher auf dem Schreibpfad, DB-Parameter binden.
5. Pro Ticket die angegebenen Tests; pro abgeschlossener Welle die vollständigen Checks aller berührten Services. Unveränderte Services nicht erneut testen.
6. Ergebnis maximal 15 Zeilen: Ticket, Baseline, geänderte Dateien, RED-/GREEN-Befehl mit Ergebnis, offene Grenzen, Anschlussvertrag. Kein „PASS“ ohne ausgeführten Check. Fehlende DB/Browser-Abnahme ausdrücklich als offen ausweisen.

**Stopregel für das kleine Modell:** Nach zwei erfolglosen Reparaturversuchen, bei unklarer API-/Datenmigration, notwendigem Scope-Ausbau oder neuer Sicherheitsentscheidung mit minimalem Repro eskalieren. Keine wiederholte Vollrepo-Analyse. Als Senior-markierte Pakete benötigen fachliche Abnahme; das ist eine Empfehlung dieses Plans, keine jetzt angeforderte Benutzerfreigabe.

Keine Live-Datenmigration, Dienste-Neustarts, Downloads, Commit/Push oder Deployment aus diesem Plan ableiten. Implementation ist ein separater Folgeauftrag. Für Integrationstests ausschließlich isolierte Testdaten/Instanzen verwenden; niemals Mutationsproben gegen die produktive Neo4j.

## Reihenfolge und Abhängigkeiten

Die Reihenfolge ist sequenziell ausführbar; keine zusätzlichen Agenten nötig.

| Welle | Pakete in Reihenfolge | Abschlusskriterium |
|---|---|---|
| 0 – Schadensgrenzen | ~~S01~~ (erledigt), ~~S02~~ (gemergt), **S03 (implementiert; Review offen)**; I01, I02, I04, I05 | freie gefährliche Pfade begrenzt; FIRMS korrekt; keine Statusrückschreibung/Poison-Row-Ausfälle |
| 1 – verlässliche Daten | S04, I06, I03; D03, D04, D05, D01, D02, D08, D10, D11; A01, A03, A04 | keine falschen Messwerte/Zeitpunkte durch Defaults, keine Batchverluste durch eine Zeile |
| 2 – Analyse und Bedienung | L02, L03, L04, L01, L05, L06; U01, U02, U03, U04, U06, U07, U08 | Analysefelder/Trace korrekt, Replay/Picking/Races regressionsgetestet |
| 3 – restliche Härtung | D06, D07, D09, U05; A05, A06, A07, A08 | verbleibende Parser-/Darstellungsfehler geschlossen |
| Designspur – früh entscheiden | X01–X04 | konkrete Produkt-/Formatverträge; X04 ist P1, nicht bis Welle 3 aufschieben |

Harte Abhängigkeiten: **I01 → I02**, **I04 → I05 → I06**, **S02 → S03**, **S01 → L01**, **D07 + X04-Design → U05-Formatabstimmung**. D01 und D02 teilen Frontend-Anzeigecode: nacheinander integrieren. U04 erhält alle bestehenden Spatial-/Legacy-Pick-Verträge. X01 blockiert nur die Hotspot-Policyänderung, nicht D06/A03. X03 blockiert nur die URL-Policyänderung, nicht U08. A02 wird vollständig in D07 abgearbeitet.

Größe: **S** ≈ lokaler Helper/Parser; **M** ≈ mehrere Funktionen oder API→UI-Vertrag; **L/Senior** ≈ Security, Persistenz oder Formatwechsel. Keine Zeit-/Tokenzusagen. M-Pakete mit mehreren unabhängigen Fällen ausdrücklich in die angegebenen Unterläufe teilen.

## Kontextpakete

| Datei | Inhalt |
|---|---|
| [01-security.md](01-security.md) | S01–S04: Cypher, Vision, Schema-Gate |
| [02-incidents.md](02-incidents.md) | I01–I06: FIRMS, Retry, Telegram, atomare Mutation, Rehydration, Zeiten |
| [03-data.md](03-data.md) | D01–D11: Feeds, Cache, Graphfilter, Zuordnung, Health |
| [04-intelligence.md](04-intelligence.md) | L01–L06: Intents, Assessments, Toolbudget, RAG, Chunker, Berichtparser |
| [05-ui.md](05-ui.md) | U01–U08: Geometrie, Zeit, Picks, Lifecycle, Rennen |
| [06-followups.md](06-followups.md) | A01–A08, X01–X04 und historische Datenreparatur |

Jede `## ID — ...`-Sektion ist ein einzelner kopierbarer Auftrag. Beispiel: nur I01 extrahieren:

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

Kommandos immer aus dem Serviceverzeichnis. Umgebung einmal pro Welle bereitstellen: Python mit **uv 0.10.0**, `uv sync --locked --all-extras`; Frontend **Node 22**, `npm ci`. Vorhandene korrekte Umgebung nicht je Ticket neu installieren. Große Caches/Artefakte nach `/data`; vor Multi-GB-Downloads freie Kapazität prüfen.

Gezielter Pythonlauf: `uv run pytest <Testdatei> -q`; Frontend: `npm test -- <Testdatei>`. Die Ticket-Dateinamen sind vorhandene Testanker oder explizit als „neu“ bezeichnet; neue Tests am bestehenden Namensschema ausrichten.

| Service | Wellenabschluss |
|---|---|
| Backend | `uv run pytest`; `uv run ruff check app/`; `uv run mypy app/` |
| Intelligence | `uv run pytest` |
| Data-Ingestion | `uv run pytest` |
| Vision-Enrichment | `uv run pytest` |
| Frontend | `npm run lint`; `npm run type-check`; `npm test`; `npm run build` |

Zusätzlich `git diff --check` und scoped Diff-Review. Echte Neo4j-Tests für D03/I04/A04; Sicherheits-Negativtests für S01–S04 ohne Kontakt zu internen Zielsystemen. Browser-Smoke mit repräsentativen Screenshots für U01–U08 und D01/D02/D10: Datumsgrenze, Pol, Scrubber, überlagerte Picks, Layer an/aus, WorldView→Briefing→WorldView. Keine Erfolgsaussage allein aus Build oder Mocktests.

## Direkt verwendbarer Startprompt

> Implementiere ausschließlich Paket `<ID>` aus `<Datei>`. Lies diesen README-Vertrag, die dortige Ticketsektion, AGENTS.md und nur die genannten Code-/Testanker. Prüfe den aktuellen Stand; vorhandene Änderungen erhalten. Arbeite TDD: fachlich roter Regressionstest, minimale Korrektur, gezielte grüne Tests. Beachte Scope, Abhängigkeiten und Nichtziele. Keine Live-Migration, kein Deployment, kein Commit/Push. Bei den Stopbedingungen liefere einen kleinen reproduzierbaren Blocker statt zu raten. Berichte knapp mit ausgeführten Befehlen und Ergebnissen. Starte jetzt mit dem Baseline- und Regressionstest.
