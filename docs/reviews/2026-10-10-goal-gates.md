# ODIN G01–G08 — aktueller Finding- und Abnahmestand

Stand10.10.2026, Integration durch Writer01a12412-a9fe-7052-93e0-ba88db75c740.
Alle212 übernommenen Sourcepfade sind nach unabhängiger Bundleprüfung in fünf
scoped Commits bis9ddf099 gesichert; begrenzte Integrationskorrekturen folgen
bis2b7de93. Der ganze Auftrag bleibt aktiv und unvollständig.
Hauptcheckout813594a/3 und fremdes Worktree7c190c0/18 sind frisch unverändert.
Kein Push/PR/Merge/Deploy. Ein unbeabsichtigter produktiver Redis-Testzugriff
ist unten ausdrücklich dokumentiert; keine historische Reparatur ausgeführt.

## Gesamtmatrix

| Goal/Finding | Source-/lokaler Beleg | Verbleibendes Abschlussgate |
|---|---|---|
| G01 DEP-01 | Vorgängerinventar; digest-/mount-/revision Releasevertrag; frische Git-/Speicherprüfung | aktuelle Runtime-/Remoteaufnahme, finaler Manifest-/Rollbackbeleg; altes Inventar ist kein heutiger Livebeleg |
| G02 Betrieb/Recon/Tracing | versionierte Codeimages, optionaler Reconmodus, gebakene Tracingkette; fünf Commit-Buildkontexte einschließlich Vision mit Schutzvertrag | gleicher finaler Commit für alle Images, echte Smokes, freigegebener Rollout/Rollback und geladene Revisionen; Recon503 nur historisch beobachtet |
| G03 CI/Artefakt | Mypy/locked Images/Built-SPA und alte6 Browserfälle im Vorgänger geprüft; neue isolierte A08/Reportfixtures in disposable CI; neue Browserfälle vorbereitet | grüne CI/CodeQL/DB-/Image-/Built-Browserchecks am finalen lieferbaren Head |
| G04 B06 A03/D06, X01/X02 | Messausfall erhält Vorwert/Zeit; Nulltext; sichtbare FIRMS-/Military-Abdeckung | X01 Stufen/IDs/Taiwangeo; Source-/Fullservice-/PR-/Liveabnahme; Cachezeit kein Messfrischebeleg |
| G04 B07 A07/A08 | UTC-Minute/FIRMS-Legacydedup; eindeutige Locationaltkeys und Konfliktabbruch |15 echte Neo4jfälle/Concurrency, historische Migration separat, Bündel-PR |
| G04 B08 L01/L02/L03 | präziser Intent, feldweise Assessmentdiagnose, tatsächliche Toolstartbudgetgrenze | vollständiger LangGraph-/Modelllauf, Servicegesamtgate, Bündel-PR |
| G04 B09 S04/L04/L05 | Schemafreigabe nach Erfolg; Poisonhit-/Scoreisolation; terminiertes Chunking | reale Store-/Count-/ACK-/Retryprüfung; keine Cross-store-Atomicitybehauptung; Bündel-PR |
| G04 B10 L06/D09 | Berichtparser/Legacyalias; Adminfallback; deterministische Reports | Endpoint/Servicegesamtgate und Bündel-PR |
| G04 B11 U01–U04 | Datumsgrenze/Pol/Originalkoordinaten; Zeitraster; operational Pickpriorität | echter Built-Browser/Canvas/nativeGPU/Human und Bündel-PR |
| G04 B12 U06–U08, X03 | HTTP-Antwortgenerationen, Detailwechsel, atomare SSE-Snapshot-/Live-Menge | X03 URL-Mehrdeutigkeit, Built-Browser/Recovery/Human und Bündel-PR |
| G04 B13 D07/A02/U05 | kanonischer Decoder, Referenzpropagator, echte Cesiumuhr/Lifecycle | Fullservice/Built-Browser/Canvas/Human, Bündel-PR; unveränderte Referenzen nicht erneut prüfen |
| G05 X04/GP | DEC-005; Produzent→Proxy/Cache→Produktionsadapter→finitePosition100651, ISS bleibt; neue Cachegeneration/defaulttle | Feed-/Redisserver-/Built-Canvas/Image/finalHead/Live; neue Formataktivierung gesondert, keine Abdeckungs-/Faktenfreigabe |
| G06 ANA-01 |12 eingefrorene Fälle, Produktionsseams/Evaluator/Runner; Assessment-/Zeitachsen bis gespeicherter Nachricht und UI | echter Graph-/Modell-/Retrieval-/Lastlauf, Originalversionen, menschliche Antwortabnahme |
| G06 Originale/R01 | drei offene FIRMS-IDs/6 Referenz-SHA,0Originale/0geschlossen; GrayFlaglokal identifiziert, Primär403; Dry-runvertrag | Originalversion/Einzel-ID-Status bleibt offen, keine globale Faktenfreigabe; R01Apply/Backup/Restore nur gesondert freigegeben |
| G07 TASK-114/UI-01 | Flightcaps250/600/1500; Eventaggregate mit exakter Mitgliederzahl/Detailpicks;10k Produktionsselektorbeleg | repräsentative Live-Dichte, echter Browser/Canvas, identischer nativer Vorher-/Nachherlauf und Mensch |
| G08 Registry/Architektur/Module | kompakteRegistry/24Briefings und vollständige Dokumentkörper erhalten;116 Katalog-/25 WorldViewdeklarationen getrennt;18 Worktrees/15 laufende Container frisch read-only inventarisiert; RemoteMaina47da45; gezielte transitive Updates mit frischem npm-Audit0 | finaler Head/Kompatibilität; Eigentümerabnahme vor jeder fremden Bereinigung; keine Worktrees gelöscht |

Jedes HN-Bündel hat einen eigenen Source-Review2026-10-10; ein Review ist kein
Bündel-PR. Diese Matrix ersetzt keine Einzel-REDs, Gates oder Autorisierungen.
Alle Detailverträge stehen weiterhin in Goal.md/HN-Plänen und TASKS.md.

## Integrationsbelege und verbleibende finale Prüfungen

Artefakte stehen unter
`/data/odin-goals/2026-10-09-repo-hardening/evidence/integration-20261010`.
Sourcecommit, Testhead und laufende Image-/Produktivrevisionen getrennt halten.

- Erste Vollsuites auf9ddf099: Backend1102PASS/2FAIL, Intelligence731PASS/1FAIL,
  Ingestion1831PASS/1FAIL/23 opt-inLive deselected, Vision44PASS. Import-/Runtime-
  Fixturefehler und unsichere Storeautodiscovery wurden begrenzt korrigiert;
  keine fachlichen Assertions gelockert. Alle betroffenen Fullsuites müssen
  auf dem folgenden sauberen gemeinsamen Head erneut bestehen.
- Echte disposable Neo4j-Verträge: Backend44PASS einschließlich12A08- und
  vierReportfällen; Ingestion8PASS einschließlich3A08-Fällen. Zusätzlich der
  vollständige GDELT-Forwardvertrag gegen eigene Neo4j/Redis/Qdrant1PASS.
  Diese Läufe waren noch auf dirty Source; finale Wiederholung bleibt Pflicht.
- Neuer GDELT-Schutz: sechs explizite Inputs, lokale eigene Storeports, feste
  Testcollection und alle drei Instance-Marker vor jedem Write.12Guardtests
  fachlich RED/GREEN; bestehender Live-Opt-in ersetzt produktive Autodiscovery.
  Der echte Forwardtest bleibt ausdrücklich ausführbar und wurde ausgeführt.
- Built-Browser9ddf099:7PASS/3FAIL. Trace/CDPprofiling belegte synchronen
  GPU-Canvasreadback bei Flugzeugicons sowie eine Quellenanzeige über dem
  Suchknopf. CPU-Readback und pointerdurchlässiger Status korrigieren diese
  Ursachen. Recovery mit unverändertem20sGate und GP100651 mit echtem
  Canvaspick/Orbit/Sourceabdeckung/Remount danach einzeln PASS. Kamerazoom-
  richtung und Öffnen des nach Remount geschlossenen Layerspanels korrigieren
  nur den realen Bedienablauf; Auswahl-/Dichteassertions bleiben unverändert.
  Gesamter Built-Browserlauf am finalen Head bleibt offen, nativeGPU/Human separat.
- Gemeinsamer Integrationsheadbc1020d: Intelligence732, Ingestion1843,
  Vision44 und disposable Backend44/Ingestion8/GDELTforward1 PASS. Built-Browser
  9PASS/1FAIL: der erste Aircraftklick unterbrach den1.6sSuchkameraflug und
  wählte die darunterliegende Länderfläche. Screenshotbeleg zeigt den Ring
  am vollständigen Ziel. Die Fixture wartet jetzt auf tatsächlich gerenderte
  Ringpixel und klickt diese; Aircraft/Vesselproben beide PASS. Keine geheimen
  Viewerhooks oder injizierten Picks; Unknown- und Requestassertions erhalten.
  Backend1102PASS/2DefaulttestFAIL wurde durch getrennte Testenvinstanziierung
  korrigiert,17Konfigurationstests mit sicheren Endpointoverrides PASS.
  Diese zusätzlichen Sourceänderungen verlangen noch den finalen Gesamtheadlauf.
- Gezieltes npm-Lockupdate verändert acht transitive Knoten in fünf Paketen;
  frischer Audit5→0. npmci/Lint/Repo-/Browsertypen und870Tests mit diesen
  Dependencies PASS. Keine pauschale auditfix-/Majoraktualisierung.

## Belegter Stand vor Integration (historisch)

- Frontend137Dateien/870Tests, ESLint, Repo-/Browsertypen und Vitebuild grün.
- G06 Intelligencefokus72 und Ruff; Backendfokus28/Ruff/Mypy95 grün.
- Neuer G02-Buildvertrag11Tests plus Visionverträge; zusammen mit relevanten Source-/Lock-/Vendor-
  Nachbarn59PASS. Echter dirty Plan vor Docker abgewiesen, kein Imagebuild.
- Vision44Fulltests/Ruff nach Imagequellen-Slice; Ingestion-/Backend-/Intelligence-
  Fullsuite bleibt explizit offen. Nicht überlappende Counts nicht addieren.
- Vier neue Report-DBfälle collect-only,15 A08-DBfälle collect-only; zwei
  CI-Jobs statisch geprüft. Neue GP/Dichtebrowserfälle nur typgeprüft.

Quelle/Test/Commit/Image/Live/Fakten/nativeGPU/Human bleiben getrennt. Gebaute
Vorgängerimages und sechs alte Browser-Smokes gehören zu ihren früheren Heads;
sie qualifizieren den heutigen dirty Sourcebaum nicht.

## Historische Ausführungsgrenzen und aktuelle Fortsetzung

Im beendeten Vorgänger verhinderte Gitindex/index.lock read-only den scoped Commit;
kein Index-/Repositorywechsel als Umgehung. Remote-DNS/Dockerzugriff blockieren
neue Remote-/Image-/Livebelege. Listen und socketpair.send EPERM blockieren
Preview/Browser sowie Executor-/Threadwakeup in Fullservice/LangGraphtests.
Diese Ursachen wurden begrenzt reproduziert; keine unveränderten Reproläufe,
Librarypatches/Skips, Alternativdaemon-/Browser-/Netzwerkumgehung. Der exklusive
Servicewriter wurde tatsächlich beendet. Seine Fehler sind historische
Umgebungsbelege. Der aktuelle reguläre danger-full-access/never-Writer kann
Index, Remote, Docker und Listen nutzen; keine Konfiguration/Hooktrust geändert,
keine aktuelle Toolrejection umgangen, keine weitere Session gestartet.

Beim ersten Ingestion-Volltest aktivierte der vorhandene Test reale Stores
automatisch. Vor Neo4j-Authabbruch schrieb er drei produktive Redis-Testschlüssel
`gdelt:slice:99999425120000:{events,mentions,gkg}:parquet` auf `done` ohne TTL.
Vorwerte sind unbekannt; Read-only-DUMP/PTTL-Belege sind gesichert. Keine
erfolgreiche Neo4j-Transaktion/Qdrantmutation in diesem Fehlerpfad. Die gezielte
Entfernung wurde ausdrücklich gefragt und bleibt ohne Antwort unerlaubt;
keine automatische Löschung/Rücksetzung. Neue Guards verhindern den Defaultpfad.

X01/X03 konkret vorbereitet und bereits gefragt, Antworten fehlen. Kein
stillschweigender Beschluss durch Zeitablauf. Deployment/Data-/Main-Merge-
Freigaben werden erst für einen vollständig gebauten/geprüften Kandidaten
mit konkret belegtem Rollback gefragt; dieser Kandidat fehlt noch.
Die [Abnahmeunterlagen](../operations/goal-acceptance-2026-10-10.md) sind
unbewertet. Gesamtabnahme darf deshalb nicht complete heißen.

Nächster Integrationsschritt:
sauberer gemeinsamer Head mit CI/Fullservice/isolierteDB/Built-Browser; alle finalen
Images aus exakt dem Commit und Manifestdigests; separate Modell-/Retrieval-/
Original-/nativeGPU-/Menschspuren. Geschützte Worktrees, produktive Dienste,
vorhandener lokaler LLM und eingefrorene Daten bleiben erhalten.
