# ODIN Releaseinventar und Rolloutvertrag

Stand: 09.10.2026, 21:25 UTC. G01 ist als Bestandsaufnahme abgeschlossen;
DEP-01 und der produktive Release bleiben offen. Keine Dienste oder Daten geändert.

## Ergebnis

Main `a47da45f3a2f4c4539296bb120b7ce402b69b1f5` enthält B01–B05 und hat
erfolgreiche CI/CodeQL-Läufe. Der laufende Stack ist kein nachgewiesener Release
dieses Commits. Backend und Intelligence antworten; die zehn konfigurierten
Ingestion-Frischeprüfungen sind grün. Das beweist weder neue Sicherheitsfixes im
Prozess noch Publikationsfrische oder vollständige fachliche Abnahme.

Die Zielarbeitskopie ist `/data/odin-worktrees/goal-release`, Branch
`feat/odin-release-provenance-20261009`. Der alte Hauptcheckout bleibt unverändert
auf `813594a`, einschließlich seiner drei unversionierten Dateien. Der Fetch
hat ausschließlich Remote-Refs aktualisiert. Nun sind 18 Worktrees registriert,
davon genau einer für dieses Goal. Zwei fremde Worktrees sind zusätzlich zum
Hauptcheckout dirty und werden erhalten.

## Ziel und vorhandene App-Dienste

| Dienst | Aktuelles Image-ID-Präfix | Vergleich mit Main | Prozess-/Buildrevision |
|---|---|---|---|
| Backend | `2d943680ddf5` | 67/93 ausgewählte Dateien gleich; 25 verschieden, 1 fehlt; Locks gleich | nicht exponiert; Code aus altem Bind-Mount |
| Intelligence | `ad6bf14d6458` | 43/55 gleich; 11 verschieden, 1 fehlt; pyproject und Lock verschieden | nicht exponiert; Image plus lokale Tracing-Ergänzung |
| Spark-Ingestion | `741ee72c1d12` | 127/149 gleich; 15 verschieden, 7 fehlen; Locks gleich | nicht exponiert; aktuell weiterhin alter Image-Code |
| Frontend | `d1d45e98c589` | 168/177 gemountete Quell-Dateien gleich; 7 verschieden, 2 fehlen | ausgelieferter Nginx-Build ohne eingebettete Revision |

Verglichen wurden Git-getrackte Python-Anwendungsdateien bzw. Frontend-Quellen
und Dependencydefinitionen, keine Tests. Bei Ingestion sind einige fehlende
Catalog-Buildtools laut Dockerfile absichtlich nicht enthalten; die Zählung
beweist deshalb nicht sieben notwendige fehlende Runtime-Module. Sie ist ein
Dateiinventar. `vision_transport.py` in Intelligence und `_persisted_time.py`
im Backend fehlen tatsächlich gegenüber Main und gehören zur Fixhistorie.

Dateihashes identifizieren vorhandene Dateien, keine geladenen Python-Module.
Für alle vier App-Container fehlen OCI-Revisionlabels. Ohne Prozessrevision
bleibt die vollständige Laufzeitprovenienz offen.

Frontend-Präzisierung: PID-Startkommando ist Nginx, kein Vite. Die öffentlich
ausgelieferte Indexdatei stimmt mit `/usr/share/nginx/html/index.html` überein;
sie referenziert `/assets/index-S2P8uOFN.js`. Der zusätzliche `/app/src`-Mount
beweist keinen Zusammenhang mit diesem kompilierten Asset. Zum Release gehören
deshalb Buildrevision und Hashes des ausgelieferten Artefakts.

## Modelle, Daten und Betriebsvarianten

- Lokal werden `qwen3.5` und `munin` serviert; Intelligence meldet beide als
  vorhanden. Spark serviert `Qwen/Qwen3.8-27B`; dies stimmt mit dem ausgewählten
  Ingestion-Modell überein. SSH bestätigt den Spark-Container auf vLLM 0.27.1.
  Die API-Modell-ID beweist keinen vollständigen Weight-/Adapterhash.
- Embed und Rerank laufen als eigene Dienste. Ihr bestehendes Modell-/Hardware-
  Setup wird bei einem App-Release erhalten; kein zweites lokales LLM starten.
- Qdrant `odin_intel` meldete 4.338.809 Punkte, dense 1024/Cosine und die
  vorhandenen spatial-/Quellen-/Ingestionsindizes. Das ist eine Live-Zählung,
  nicht die 4.166.333-ID-Kopie der eingefrorenen Korpusqualifikation.
- Neo4j bestätigt Uniqueness für Entity(name,type), Event(event_key),
  Incident(id), Location(loc_key), Report(id) und Report(scope_key).
  `hapi_document_id_unique` ist **nicht vorhanden**. Vor parallelen neuen
  HAPI-Schreibern ist die dokumentierte operator-run Voraussetzung gesondert
  zu prüfen und autorisiert anzuwenden; kein beiläufiger Schema-Write.
- Spatial-Catalog, Aktivierungs-/Coverage-Dateien, Telegramzustand und GDELT-
  Persistenz sind separate Laufzeitinputs. Ihre Revisionen/Hashes müssen im
  Release-Manifest gebunden werden. Code-Rollback stellt Daten nicht zurück.
- Intelligence verwendet zusätzlich lokale Tracing-Compose-Dateien und
  read-only/runtime Mounts. Die zugehörige fremde Arbeitskopie ist dirty.
  Ein generischer Main-Rollout darf diese Erweiterungen nicht still verlieren.
- Recon meldet HTTP 503: Manifest nicht geladen. Das Manifest ist optional;
  derzeit ist die Aktivierung gegenüber der Frontend-Vorauswahl uneindeutig.
  G02 muss optional-inaktiv sichtbar abbilden oder einen gültigen Manifest-/
  Assetbestand vor dem Start bereitstellen.

## Kompatible Rolloutfolge

Dies ist die konkrete Reihenfolge für einen späteren geprüften Release;
es gibt noch keine Freigabe oder gebauten Kandidaten. Vor der Freigabe wird
daraus ein ausführbarer, am isolierten Stack geprüfter Rollout.

1. G02 erstellt eine explizite Betriebs-Compose-Konfiguration: Images enthalten
   Code, Inputs sind separat gebunden, OCI-/Prozessrevision und Frontend-Build-
   Metadaten sind nachweisbar. Bestehende Tracing-Erweiterungen inventarisieren
   und explizit kompatibel übernehmen. Keine Credentials in Manifest/Logs.
2. Am finalen Commit alle App-Images bauen und Image-IDs/Digests, Locks,
   Modelle/Adapter, Catalog-/Codebook-/Cacheversionen in ein Release-Manifest
   schreiben. Service-, Image-, Schema- und Browserchecks ausführen. Noch keine
   Datenmigration; Cache-Generation bleibt kompatibel, neue Formate versioniert.
3. Aktuelle Images/Compose-/Konfigurationsreferenzen und relevanten Persistenz-
   Zustand sichern; Snapshot-/Restorebelege prüfen. HAPI-Voraussetzung separat
   prüfen. Wenn eine Daten- oder inkompatible Cacheänderung nötig wird, braucht
   sie eigenen Dry-run, Freigabe und Rücknahmeweg.
4. Nutzerfreigabe für genau diesen App-Release mit Zeitfenster und Rollback
   einholen, falls noch nicht belegbar erteilt. Keine DB-/GPU-/fremden Dienste
   neu erstellen. Neue Ingestion zunächst nicht parallel mit dem alten Writer
   aktivieren; Drain-/Startfolge wird vor Ausführung festgelegt.
5. Nach Drain Intelligence, Backend und Frontend aus demselben Release einsetzen;
   Consumer-/API-Kompatibilität vor aktivem Ingestionwechsel bestätigen.
   Ingestion danach genau einmal mit korrektem Spark-/Codebook-/Catalog-Vertrag
   aktivieren. Stateful Core und Modellruntime bleiben erhalten.
6. Pro gestarteten Prozess Revision/Digest, Health/Readiness, Query-/Report-
   Kernpfade, Quellenfrische und Fehlerverhalten prüfen. Browser tatsächlich
   ausgelieferte Buildrevision, Messwerte, Scope, Zeitwahl, Picking und
   WorldView→Briefing→WorldView nachweisen. Kurzen vorab definierten Soak messen.

## Rollback und Stopbedingungen

Zurücknahme erfolgt auf die gesicherten alten Image-IDs und Konfigurations-
referenzen, einschließlich Tracing-Mounts und unverändertem Modellvertrag.
Betroffene eigene Prozesse drainen und gezielt ersetzen, keine globale
Compose-down-/GPU-Swap-Aktion. Alten Writer erst nach Beendigung des neuen
aktivieren. Health, Quelleingang und Kernpfade danach prüfen.

Bei falsch exponierter Revision, fehlendem Pflichtinput, inkompatiblem Schema/
Cache, fehlendem Modell, Verlust der Tracing-Erweiterung oder fehlgeschlagenem
Kernpfad den Rollout stoppen. Ein Image-Rollback ist kein Datenrollback; ohne
separate nachgewiesene Datenrücknahme keine Datenmigration ausführen.

## Belege und nächster Schritt

Lokale Rohbelege unter
`/data/odin-goals/2026-10-09-repo-hardening/evidence/G01/`:
`inventory.py`, `inventory.json` und `schema.json`. Die Daten enthalten keine
Container-Env-Secrets; private Laufzeitpfade nicht ungeprüft extern publizieren.
Reproduktion: `python3 .../evidence/G01/inventory.py` liest Docker/Git/GETs und
überschreibt ausschließlich die eigene Inventardatei. Neuaufnahme statt altem
Zeitstempel als aktuelle Aussage verwenden.

Main-CI: https://github.com/Hunter5Thompson/OSINT/actions/runs/37529452461
CodeQL: https://github.com/Hunter5Thompson/OSINT/actions/runs/37582859881

Nächster begrenzter Schritt G02: Release-Revision als expliziten Buildinput
implementieren und in Backend/Intelligence-Prozessantworten sowie im
Frontend-Artefakt nachweisen. Fachlich rote Tests zuerst; bisherige API-Felder
bleiben kompatibel. Danach Betriebs-Compose und G03-Image-/Browsergates ergänzen.
