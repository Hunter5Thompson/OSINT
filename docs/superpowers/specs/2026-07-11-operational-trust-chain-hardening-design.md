# TASK-119 — Operational Trust Chain Hardening (Design Spec)

**Datum:** 2026-07-11

**Status:** REVIEWED — READY FOR EXECUTION

**Implementierungsplan:**
`docs/superpowers/plans/2026-07-11-operational-trust-chain-hardening-slices.md`

## 1. Problem

ODIN besitzt gute lokale Verträge — deterministische Graph-Writes, einen
Evidence-Codec, Service-Tests und einen täglichen Quality-Loop. Zwischen diesen
Verträgen bleiben jedoch Lücken, in denen ein formal gültiger Einzelzustand zu
einem falschen Gesamtsystem werden kann:

- Git, gerenderte Compose-Konfiguration und laufende Container können
  unterschiedliche Zustände darstellen.
- Intelligence kann `munin` konfigurieren, ohne zu prüfen, ob vLLM dieses Modell
  tatsächlich anbietet.
- Tests können lokale `.env`-Werte übernehmen und dadurch auf demselben Commit
  unterschiedliche Ergebnisse liefern.
- Root-/Ops-Contracts können existieren, ohne von CI oder Nightly ausgeführt zu
  werden; eine unbesessene Regel ist kein Gate.
- Ein formal gültiger Retrieval-Treffer kann inhaltlich leer, doppelt oder
  Boilerplate sein.
- Graph-Read-Templates können Beziehungen erwarten, die kein aktiver Writer
  erzeugt.
- `published_at` und gerichtete Retrieval-Qualität werden genutzt, ohne dass ihre
  Abdeckung beziehungsweise Korrektheit als Gate gemessen wird.
- ReAct-Optimierungen wären derzeit Spekulation, weil der Capture-Hook keine
  vollständige Research-Trace konserviert.

Das Ziel ist kein neues Feature. Das Ziel ist eine durchgängige, überprüfbare
Vertrauenskette vom getrackten Quellzustand bis zur synthetisierten Antwort.

## 2. Engineering Lens: Dijkstra, SDD und TDD

### 2.1 Dijkstra-Mindset

Wir reduzieren den erlaubten Zustandsraum, statt immer mehr Fehlerfälle später
zu behandeln:

1. **Ungültige Zustände unrepräsentierbar machen.** Ein konfiguriertes, aber nicht
   geladenes Synthese-Modell ist nicht „degraded“, sondern `not ready`.
2. **Invarianten vor Mechanismen.** Jeder Slice benennt zuerst den Zustand, der
   immer gelten muss. Erst danach wird eine Implementierung gewählt.
3. **Eine Quelle der Wahrheit.** Derselbe Wert wird nicht unabhängig in Branch,
   Image, Health-Antwort und Runbook gepflegt.
4. **Determinismus vor Heuristik.** Identitäten, Deduplizierung, Schema-Verträge
   und Drift-Prüfungen sind deterministisch. Heuristiken werden nur dort genutzt,
   wo der Gegenstand selbst unscharf ist, und dann mit einem festen Eval-Gate.
5. **Kleine Interfaces, tiefe Module.** Bestehende Seams werden vertieft. Neue
   Adapter entstehen nur, wenn Produktion und Test tatsächlich verschiedene
   Adapter benötigen.
6. **Keine vorsorgliche Allgemeinheit.** Kein Kubernetes, kein neues
   Deployment-Framework, keine Telemetrieplattform und keine Graph-Neumodellierung.
7. **Löschungstest.** Ein neues Modul ist nur gerechtfertigt, wenn seine Löschung
   dieselbe Komplexität über mehrere Caller verteilen würde.

### 2.2 Das gemeinsame SDD/TDD-Mantra

Für jeden Slice gilt dieselbe Reihenfolge. Sie ist ein Merge-Gate, keine
Empfehlung:

1. **SPEC** — Invariant, Interface, Fehlersemantik, Non-Goals und Abnahme werden
   vor Produktionscode festgeschrieben. Neue Erkenntnisse ändern zuerst die Spec.
2. **RED** — Ein Test am realen Seam beweist den exakten Defekt. Der rote Lauf
   und sein erwarteter Fehler werden im PR festgehalten.
3. **GREEN** — Die kleinste Implementierung erfüllt nur den beschriebenen
   Vertrag. Keine benachbarte Modernisierung.
4. **REFACTOR** — Duplikate und tote Pfade werden entfernt, ohne das Interface zu
   verbreitern. Alle Tests bleiben grün.
5. **VERIFY** — fokussierter Test, Service-Suite, statische Checks und genau der
   notwendige Runtime-Smoke.
6. **RECORD** — Spec-Status, Abnahmebeleg und relevante Betriebsdokumentation
   werden im selben PR aktualisiert.

Ein Test, der nur Strings im Produktionscode sucht, genügt nicht, wenn das reale
Interface ausführbar ist. Ein Live-Test darf niemals in den Produktionsgraphen
schreiben; dafür wird ein disposabler Adapter verwendet.

### 2.3 Emergency-Ausnahme für Slice 01

Der Munin-Compose-Hotfix lag bereits vor dieser Spec als staged Änderung im
Worktree. Er wird nicht zurückgesetzt, nur um nachträglich einen roten Test zu
erzeugen. Slice 01 behandelt den alten `HEAD`-Render als dokumentierten roten
Ausgangszustand und schreibt vor jeder weiteren Produktionsänderung die fehlenden
Vertragstests. Alle neuen Codepfade folgen normal RED → GREEN.

## 3. Ziele

- Der laufende Interactive-Pfad ist aus einem getrackten Commit reproduzierbar.
- Health und `odin.sh doctor` können Modell-, Git- und Konfigurationsdrift
  maschinenlesbar erkennen.
- CI, Images und Quality-Loop verwenden dieselben gelockten Abhängigkeiten.
- Der tägliche Quality-Loop ist unabhängig von lokalen Secrets reproduzierbar.
- `tests/ops` besitzt mit Quality-Loop und CI zwei automatische Runner.
- Standardmäßig ist kein Host-Port außerhalb des lokalen Rechners erreichbar.
- Ein Evidence-Pack enthält nur eindeutige, inhaltlich brauchbare Quellenblöcke.
- Graph-Reads werden gegen Formen getestet, die aktive Writer wirklich erzeugen.
- Graph-Integritätsmetriken unterscheiden klar zwischen strukturell isolierten
  Knoten, fehlender Dokument-Lineage und Store-Divergenz.
- Publikationszeit und gerichtetes Retrieval besitzen feste, wiederholbare Gates.
- ReAct wird erst nach vollständiger Trace-Erfassung verändert.

## 4. Non-Goals

- kein Wechsel von Docker Compose auf einen anderen Orchestrator
- keine Image-Signierung, SBOM- oder SLSA-Einführung in dieser Tranche
- kein zentrales Shared-Python-Package für alle Services
- keine Neumodellierung des gesamten Neo4j-Graphs
- keine automatische Löschung oder Reparatur von Event-Knoten
- kein neues Embedding-, Reranker- oder LLM-Modell
- keine Erhöhung des ReAct-Tool-Budgets ohne gemessenen Bedarf
- kein vollständiges Benutzer-/Rollen-Authentifizierungssystem
- keine zweite Nightly-Pipeline; der vorhandene Quality-Loop bleibt Eigentümer
- keine großen Munin-Eval-Artefakte im OSINT-Repository
- keine Aktivierung der live-server-abhängigen `tests/contract`; deren Ersatz
  bleibt TASK-118

## 5. Systeminvarianten

| ID | Invariant | Sichtbares Fehlverhalten |
|---|---|---|
| OT-01 | Jedes explizit konfigurierte LLM-Modell steht im vLLM-Modellkatalog. | Intelligence ist nicht ready; kein stiller Base-Fallback. |
| OT-02 | Tests hängen nicht von der lokalen `.env` ab und jeder TASK-119-Contract besitzt einen automatischen Runner. | Fokussierter Test, Quality-Loop und CI liefern auf gleichem Commit dasselbe Ergebnis. |
| OT-03 | Host-Ports binden standardmäßig nur an Loopback; Secret-Dateien sind nicht gruppen-/weltlesbar. | `doctor` beziehungsweise der Compose-Vertrag schlägt fehl. |
| OT-04 | Jeder Dependency-Resolver erhält einen getrackten Lockfile und läuft im Locked-Modus. | CI oder Image-Build bricht ab, statt neu aufzulösen. |
| OT-05 | Laufende Production-Container nennen Git-SHA und Compose-Zustand; Development ist sichtbar als solcher markiert. | Production-Drift endet non-zero; Development kann nie fälschlich als verifiziertes Production erscheinen. |
| OT-06 | Ein Evidence-Pack enthält höchstens einen Block je `source_ref_id` und keinen bekannten Zero-Content-Block. | Der Codec/Guard verwirft den Block deterministisch. |
| OT-07 | Graph-Read-Templates traversieren mindestens einen durch aktive Writer erzeugten Pfad. | Der Contract-Test gegen einen disposablen Graphen wird rot. |
| OT-08 | `published_at` bezeichnet ausschließlich eine belegte Publikationszeit und trägt eine Herkunft. | Unbelegte Zeit bleibt `null`; Event-Zeit wird nie hochgestuft. |
| OT-09 | Gerichtete Benchmarkfragen ranken die richtige Subjekt–Aktion–Objekt-Richtung vor der Gegenrichtung. | Das feste Retrieval-Gate wird rot. |
| OT-10 | Jeder Research-Lauf besitzt einen strukturierten Stop-Grund und eine vollständige Tool-Trace. | Capture-Validierung schlägt fehl; keine Policy-Änderung zulässig. |

## 6. Module und Seams

| Modul | Interface am Seam | Verantwortung | Kein Teil des Interfaces |
|---|---|---|---|
| Runtime Model Contract | konfigurierte Modellnamen → Readiness-Ergebnis | Modellkatalog abrufen, Pflichtmenge vergleichen, klaren Fehler liefern | vLLM-Prozessverwaltung |
| Quality Gate | Repository-Stand → Exit-Code + Report | hermetische Prüfungen in kanonischer Reihenfolge | automatische Code-Reparatur |
| Local Exposure Contract | gerendertes Compose + Dateimodus → Befund | sichere Host-Bindings und Secret-Modi prüfen | Benutzer-/Rollen-Auth |
| Dependency Contract | Manifest + Lock → reproduzierbare Umgebung | Locked-Install in CI, Image und Nightly | globale Monorepo-Dependencyverwaltung |
| Runtime Provenance | gewünschter Git-/Compose-Zustand → Drift-Befund | Build-Identität, Health-Metadaten, Deploy und Doctor | Registry, Signierung, Rollout-Controller |
| Evidence Pack | geordnete `EvidenceItem`-Liste → begrenzter Text | Quellenidentität, Qualitätsgate, Budget, vollständige Blöcke | Retrieval-Strategie |
| Graph Read Contract | Intent + Parameter → Rows | Query-Pfade und kompakte Serialisierung über Writer-Schema | Graph-Writes oder Reparaturen |
| Publication Metadata | belegte Dokumentmetadaten → Zeit + Basis | Zeit extrahieren und ehrlich kennzeichnen | Event-/Observed-Zeit |
| Direction Gate | feste Query-/Korpuspaare → Retrieval-Metriken | Richtungsfehler reproduzierbar messen | ReAct-Planung |
| Research Trace | Agent-Zustand → versioniertes Capture | Calls, Dauer, Evidence, Modelle, Stop-Grund | Telemetrie-Backend oder Policy-Optimierung |

## 7. Slice-Grenzen und Reihenfolge

```text
S01 Runtime model contract ───────┐
                                  ├──> S05 Runtime provenance + deploy
S02 Hermetic quality gate ────────┤             │
S03 Local exposure floor ─────────┤             └──> bestehender Nightly-Smoke
S04 Locked dependencies ──────────┘

S06 Evidence hygiene ───────┬──> S09 Directional retrieval ──> S10 ReAct trace
S07 Graph contract ─────────┤                                  ▲
S08 Publication metadata ───┘                                  │
                         S07 Graph context quality ─────────────┘
```

Die numerische Reihenfolge ist die empfohlene Abarbeitung. S03 und S04 sind
technisch unabhängig, werden aber vor S05 abgeschlossen, damit der
Deployment-Slice bereits auf sicheren und gelockten Inputs aufbaut. S06 startet
erst nach S05, damit sein Vorher-Snapshot einem eindeutigen Git-/Runtime-Zustand
zugeordnet werden kann; S07 darf danach unabhängig von S06 bearbeitet werden.

## 8. Zentrale Designentscheidungen

### 8.1 Readiness statt Prozess-Rennen

Intelligence beendet sich nicht sofort, nur weil vLLM beim parallelen
Compose-Start noch bootet. `/health` prüft mit kurzem Timeout die konfigurierte
Pflichtmenge und antwortet so lange nicht-ready. Dadurch bleibt Compose-Retry die
einzige Startkoordination. Ein fehlendes `munin` kann nicht als gesund gelten.

### 8.2 Hermetischer Compose-Render-Seam

Compose besitzt zwei reale Environment-Adapter: Produktion liest standardmäßig
`.env`, Contract-Tests lesen ausschließlich die getrackte synthetische Fixture
`tests/fixtures/compose.env`. Das Service-`env_file` wird deshalb über
`${ODIN_ENV_FILE:-.env}` adressiert. Render-Tests setzen sowohl
`ODIN_ENV_FILE=tests/fixtures/compose.env` als auch
`--env-file tests/fixtures/compose.env`; sie dürfen eine Host-`.env` weder
benötigen noch lesen.

### 8.3 Ein Nightly-Eigentümer und ein Contract-Eigentümer

Der vorhandene `odin-quality-loop.timer` bleibt der einzige Nightly-Eigentümer.
`odin.sh smoke` und `doctor` werden vertieft; es entsteht kein zweiter Timer und
kein zweites Berichtssystem. `tests/ops` wird als erste Testsuite des Quality-
Loops ausgeführt und erhält ab S04 einen eigenen CI-Job. Die Backend-`uv`-
Umgebung stellt den Pytest-Runner bereit; es entsteht kein sechstes Root-
Dependencyprojekt.

Live-Baseline vom 2026-07-11: Der **System**-Timer ist installiert, enabled und
aktiv; die User-Unit existiert nicht. Die installierte Service-Unit läuft als
`deadpool-ultra`, während der getrackten Unit `User=` und `Group=` fehlen und
systemd Config-Drift meldet. S02 macht die getrackte Non-Root-Unit zur Wahrheit;
ein Sync darf den funktionierenden Hostzustand nicht auf Root zurückstufen.

### 8.4 Lockfiles sind Deployment-Artefakte

Die Lockfiles von Backend, Intelligence, Vision-Enrichment und Frontend werden
wie der bereits getrackte Data-Ingestion-Lock behandelt. CI, Docker und
Quality-Loop dürfen nicht unterschiedliche Resolvermodi verwenden.

### 8.5 Production- und Development-Compose sind reale Adapter

Production führt ausschließlich im Image gebackenen Code aus. Development darf
den vorhandenen Backend-Code-Bind-Mount behalten, aber nur in einer expliziten
`docker-compose.dev.yml`. `deploy` verwendet diesen Adapter nie; ein klar
benannter Dev-Aufruf verwendet ihn immer. Der Dev-Adapter trägt einen sichtbaren
Runtime-Mode; `doctor` darf ihn nicht als SHA-verifiziertes Production melden.
Damit bleibt der schnelle Dev-Loop erhalten, ohne die Laufzeitidentität des
Production-Pfads zu verwässern.

### 8.6 Read-Path schützt sofort, Ingest verhindert Wiederholung

Bestehende schmutzige Qdrant-Payloads werden zunächst deterministisch am
Read-Seam abgefangen. Derselbe kleine Qualitätsvertrag wird anschließend am
Fulltext-Ingest angewendet. Dieser Slice führt keine destruktive Massenmutation
des Korpus aus.

### 8.7 Graph-Vertrag vor Graph-Reparatur

`Event ohne DESCRIBES`, `NOT (n)--()` und `Qdrant-URL ohne Document` sind drei
verschiedene Zustände. Der Report benennt sie getrennt. Erst ein späterer,
eigens spezifizierter Repair-Slice darf daraus Lösch- oder Reingest-Aktionen
ableiten.

### 8.8 Beobachten vor Eingriff und vor ReAct-Steuerung

S10 ändert keine Recherchepolitik. Er endet mit einem gemessenen Datensatz und
einer Entscheidung: kein Handlungsbedarf, deterministischer Controller oder
separate Policy-Distillation. Diese Entscheidung erhält bei Bedarf eine neue
Spec; sie wird nicht vorweg implementiert. Vor S06 konserviert ein kleiner
10-Query-Lauf mit dem bereits aktiven Capture-Hook die verfügbare Vorher-
Baseline. S10 erzeugt nach den Daten-Slices die vollständige 30-Query-Trace; die
beiden Messpunkte werden nur über Felder verglichen, die in beiden Formaten
existieren.

## 9. Globale Verifikationsregeln

Jeder Slice führt nur die betroffenen Suites aus, danach jedoch mindestens:

```bash
# Root/Ops über die bestehende Backend-Testumgebung
(cd services/backend && uv run pytest ../../tests/ops -q)

# Backend
(cd services/backend && uv sync --locked --all-extras && uv run pytest)

# Intelligence
(cd services/intelligence && uv sync --locked --all-extras && uv run pytest)

# Data Ingestion
(cd services/data-ingestion && uv sync --locked --all-extras && uv run pytest)

# Frontend/Vision nur bei Berührung
(cd services/frontend && npm ci && npm run lint && npm run type-check && npm test)
(cd services/vision-enrichment && uv sync --locked --all-extras && uv run pytest)
```

`--locked` und `npm ci` werden ab S04 verbindlich. Vor S04 gelten die heutigen
Kommandos aus `AGENTS.md`, damit frühere Slices nicht künstlich blockieren.

Ein Runtime-Smoke darf nur in Slices vorkommen, deren Invariant tatsächlich
Laufzeitzustand betrifft. Unit-Tests werden nicht durch manuelle Smokes ersetzt.

## 10. Stop-Regeln

Ein Slice stoppt und ändert zuerst seine Spec, wenn:

- der rote Test den beschriebenen Defekt nicht reproduziert,
- die Implementierung ein neues externes System oder einen neuen Daemon benötigt,
- eine Migration Daten löschen oder semantisch umdeuten würde,
- mehr als ein unabhängiger Defektmechanismus repariert werden müsste,
- ein bestehendes öffentliches Interface geändert werden müsste, das nicht in der
  Slice-Spec steht,
- ein „temporärer“ Fallback die Invariant abschwächen würde.

## 11. Definition of Done für TASK-119

- Alle zehn Slices sind einzeln gemergt und in `TASKS.md` als erledigt markiert.
- Jeder Slice besitzt einen dokumentierten RED-Beleg und einen grünen
  Abnahmebefehl.
- Alle `tests/ops` laufen sowohl im Quality-Loop als auch in CI; kein TASK-119-
  Contract ist manual-only.
- Der vollständige Quality-Loop läuft mit gelockten Abhängigkeiten grün.
- `odin.sh doctor` meldet im Production-Mode keinen Git-, Compose-, Modell- oder
  Exposure-Drift; Development wird ausdrücklich als nicht production-verifiziert
  ausgewiesen.
- Der Interactive-Smoke beweist Base-Tool-Calling und Munin-Synthese.
- Die acht vorhandenen Canary-Captures enthalten keine doppelten Quellen,
  Hashtag-only-Evidenz oder `None`-Graphknoten.
- Graph-Read-Contracts laufen gegen einen disposablen Writer-Fixture-Graphen.
- Das Datums- und Richtungs-Gate erfüllt seine in den Work Orders festgelegten
  Schwellen.
- ReAct besitzt mindestens 30 valide strukturierte Traces; eine Folgemaßnahme ist
  evidenzbasiert entschieden oder explizit verworfen.
