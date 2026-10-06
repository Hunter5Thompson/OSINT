# ODIN: Datenfrische, Analysequalität und laufender Code

Stand: 06.10.2026, Messfenster ab 20:33 UTC. Dieser Bericht ist eine erste
begrenzte Betriebsprüfung zusätzlich zur [B05-Abnahme](../reviews/2026-10-06-hn-b05-acceptance.md).

**Daten kommen an und die Oberfläche funktioniert. Der laufende Codestand ist
älter als Main. Die Analyse kann relevante Belege finden und unbelegte Aussagen
zurückweisen, vergibt aber auch ohne Beleg eine Gefahrenstufe.** Damit ist die
umfassende Betriebs-/Qualitätsabnahme noch offen.

## Datenfrische: zehn konfigurierte Qdrant-Quellen innerhalb ihrer Grenzen

`GET /api/health/feeds` meldete am 06.10. um 20:33:27 UTC alle zehn konfigurierten
Quellen als `fresh`. Gemessen wird die letzte Ingestion, nicht die Publikationszeit.

| Quelle | Alter bei Messung | Konfigurierte Grenze |
|---|---:|---:|
| GDELT GKG | 185 s | 1 h |
| RSS | 1.029 s | 2 h |
| RSS-Volltext | 13.730 s | 6 h |
| Telegram | 2.005 s | 6 h |
| FIRMS | 873 s | 12 h |
| USGS | 6.473 s | 24 h |
| EONET | 6.524 s | 3 Tage |
| GDACS | 6.512 s | 3 Tage |
| PortWatch | 28.126 s | 14 Tage |
| UCDP | 943.823 s | 45 Tage |

Eine zweite Messung um 20:41:36 UTC blieb `ok`; FIRMS hatte seit der ersten Messung
neue Ingestion. Je zwei aktuelle RSS-, USGS- und GKG-Payloads wurden unabhängig
lesend aus Qdrant geprüft. Der später abgefragte Gray-Flag-RSS-Artikel lag vor:
publiziert 19:44 UTC, eingegangen 20:16:10 UTC. GKG hatte `published_at=null`;
hier ist Publikationsfrische aus dieser Stichprobe nicht belegbar.

Grenzen: Ein aktueller Schreibzeitpunkt beweist keinen aktuellen Quelleninhalt
und keine vollständige Abdeckung. Die Quelle UCDP gilt selbst nach rund elf Tagen
noch als fresh, weil der konfigurierte Grenzwert 45 Tage beträgt. Flugzeuge,
Schiffe und Orbitdaten sind nicht durch diesen Zehn-Quellen-Bericht abgenommen.
Weitere API-Stichprobe: 1.500 Flüge, 500 Militärtracks und 15.958 Satelliten.
Die 500 Tracks sind eine begrenzte Antwort, keine Vollständigkeitsmessung.

## DEP-01: Dienste verwenden nicht den aktuellen Main-/B05-Stand

**Priorität P1; offen.** Remote-Main ist `1359d14` (B04). Backend und Frontend
binden Code aus `/home/deadpool-ultra/ODIN/OSINT` ein; dieser Checkout steht auf
`fix/hn-s01-cypher-guardrails`, `813594a`.

Dateiinhalte im Container wurden per SHA-256 und Bytevergleich mit Git geprüft:

- Backend `routers/graph.py` und `incident_promoter/cluster_store.py` entsprechen
  dem alten Checkout, nicht aktuellem Main.
- Frontend `FlightLayer.tsx` und `aircraftIcons.ts` entsprechen nicht B05.
- Spark-Ingestion `military_aircraft_collector.py` und
  `nlm_ingest/write_templates.py` entsprechen dem älteren Stand, nicht Main/B05.
- Intelligence `agents/tools/graph_query.py` entspricht nicht aktuellem Main.
- Für die vier geprüften Dienste fehlt ein OCI-Revision-Label. Die Container
  wurden am 26./27.09. erstellt und zuletzt am 28.09. gestartet.

Auswirkung: Ein Merge ist kein Nachweis, dass die Fehler im Betrieb behoben sind.
Für Python beweist ein Dateihash nur den Dateistand, nicht sämtliche bereits
geladenen Module. Es wird daher kein exakter globaler Deployment-Commit behauptet.
Die Flüge-Stichprobe lieferte keine null-Messwerte und Kontaktzeiten innerhalb
eines engen Zeitbands. Das alte Aircraft-Modell hat einen `now()`-Default; diese
Kontaktzeiten sind ohne zusätzliche Quellprüfung kein belastbarer Frischenachweis.

Nächste Schritte: aktuellen und gewünschten Release pro Dienst erfassen,
reproduzierbaren Build/Rollout mit Rollback vorbereiten, dann gezielt nachweisen,
dass B01–B05 tatsächlich geladen sind. Abgeschlossen erst mit Runtime-Provenienz
und Verhaltenstests nach einem gesondert freigegebenen Deployment. Kein Neustart,
Build eines Live-Images oder Deployment wurde durch diese Prüfung ausgeführt.

## ANA-01: Gefahrenstufe trotz fehlender Evidenz

**Priorität P1; offen, zwei Live-Stichproben.** Beide Aufrufe über
`POST /api/intel/query` ohne Report-ID; keine Berichtspersistenz angefordert.

1. Suche nach vorhandenem Gray-Flag-Artikel: **53,31 s**, lokaler Qdrant-Toolpfad,
   korrekte Kernaussage zu E-2D/Gray Flag/Ventura County, Datum und passende URL.
   Fehlender Übungszeitraum wird benannt. Zusätzliche Randtreffer und eine
   unverifizierte NotebookLM-Bewertung machen die Antwort länger als angefragt.
   Confidence 0,6; Gefahrenstufe `MODERATE`.
2. Absichtlich unbelegte NATO-/Mars-Waffenstillstandsbehauptung: **41,80 s**,
   Qdrant plus Graph-Tool, ausdrücklich nicht belegt, Confidence 0,3.
   Trotzdem `MODERATE`, begründet mit einem hypothetischen Risiko.

Auswirkung: Der Text kann fehlende Evidenz ehrlich benennen, während die
Gefahrenklassifikation dennoch eine scheinbar bewertete Lage erzeugt.
Ein Live-Erfolg belegt zudem weder allgemeine Retrieval-Präzision noch robuste
Halluzinationsvermeidung. Die Tool-Traces beider Proben zeigen keine Websuche.

Nächste Schritte: Rubrik für unbelegte Behauptungen und Evidenzmangel festlegen;
kleines versioniertes Set aus belegten, unbelegten, veralteten und widersprüchlichen
Fällen mit Dokument-IDs/URLs, erwarteten Enthaltungen und Zeitbezug erstellen.
Erst danach gegen den tatsächlich deployten Release messen und durch Menschen
fachlich bewerten. Anschluss an B08/B09, kein pauschaler Promptfix in B05.

## UI-01: Oberfläche erreichbar, Globe bleibt schwer lesbar

**Priorität P2; offen.** Ungefixtureter Playwright/Chromium-Lauf gegen Port 5173
in 1440×1000 und 1280×800: keine JavaScript-Ausnahme. WorldView → Briefing →
WorldView entfernt den Canvas und erzeugt anschließend genau einen. API-/SSE-
Kernaufrufe antworten mit 200, die Chronik zeigt `global · complete`.
Ein abgebrochener Signalstream beim Seitenwechsel ist erwartete Cancellation.

Die Screenshots zeigen viele sich überlagernde Flugzeugsymbole am Globusrand
und dichte Spuren. Rendering funktioniert; gute Lesbarkeit ist damit nicht
abgenommen. Anschluss: bestehender TASK-114-Declutter-Umfang. Abgeschlossen erst
mit nachvollziehbarer Dichte-/LOD-Policy und visueller Abnahme an repräsentativer
Live-Dichte. SwiftShader beweist keine native RTX-5090-Performance.

## UI-02: Rekonstruktionsszenen nicht verfügbar

**Priorität P2; offen.** `GET /api/recon/scenes` antwortet im Live-Browser mit 503;
der übrige Globe bleibt nutzbar. Ursache/gewollter Betriebsmodus noch nicht geprüft.
Nächster Schritt: Konfiguration und Manifestpfad lesend prüfen, erwartete optionale
Nichtverfügbarkeit von echtem Defekt unterscheiden und Nutzeranzeige abnehmen.

## CI und Fortsetzung

Die zuvor wegen fehlender Hosted-Runner unvollständige Main-CI wurde mit
`gh run rerun 37369017610 --failed` wiederholt und ist jetzt vollständig grün.
Der dynamische CodeQL-Main-Lauf `37369017186` ließ sich nicht auf demselben Weg
wiederholen; CLI meldete, sein Workflow sei möglicherweise nicht wieder ausführbar.
Das beweist keinen CodeQL-Codefehler. Neuer B05-PR prüft seinen eigenen Head.

Nächste Reihenfolge: B05-PR/CI zur Mergeentscheidung vorlegen; DEP-01 als
Voraussetzung der weiteren Betriebsabnahme klären; Qualitätsrubrik und breitere
Frischenachweise vorbereiten. B06, Live-Reparaturen und Produktentscheidungen sind
damit nicht automatisch gestartet oder freigegeben.

Reproskripte, Rohprotokolle, Dateihashes und Bilder liegen unter
`/data/odin-b05-acceptance-20261006/`: `deployment.json`, `live-feed-health*.json`,
`analysis-results.json`, `live-browser-result.json` und zugehörige `*_probe.py`.
