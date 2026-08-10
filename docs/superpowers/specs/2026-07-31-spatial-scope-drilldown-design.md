# ODIN Spatial Scope — modularer Spec-Index

- **Erstfassung:** 2026-07-31
- **Modularisiert:** 2026-08-01
- **Freigegeben:** 2026-08-01
- **Status:** Spatial Core umsetzungsfreigegeben; zweites Cinematic-Required-Fixes-
  Set eingearbeitet, unabhängiger Abschluss-PASS ausstehend
- **Betroffene Systeme:** Hlidskjalf/WorldView, Backend, CHRONIK, Neo4j, Qdrant, Munin/Intelligence und Data Ingestion
- **Entwurfsart:** Clean-room. Aus dem externen Repository stammt ausschließlich die allgemeine Idee hierarchischer räumlicher Scopes. Quellcode, Assets, Daten, Prompts, Gestaltung, Attributionen und Lizenztexte werden nicht übernommen.
- **Ausführungspläne:** [Implementation-Plan-Index](../plans/2026-08-01-spatial-scope-implementation.md)
- **Cinematic-Erweiterung:** [Cinematic WorldView](2026-08-10-cinematic-worldview-design.md),
  Draft nach zwei adversarialen Review-Runden; bis zum unabhängigen Abschluss-PASS
  nicht umsetzungsfreigegeben

Diese Datei ist bewusst nur Einstieg, Navigationskarte und Präzedenzregel. Die
normativen Verträge liegen in den verlinkten Teil-Specs. Ein Agent soll nicht den
gesamten Satz laden, sondern nach dem untenstehenden Review-Pfad nur die benötigten
Module öffnen.

## Entscheidung

ODIN erhält ein rendererunabhängiges `SpatialScopeModule`, das einen kanonischen
räumlichen Scope (`world → country → admin1 → admin2`) atomar auflöst und als
unveränderlichen Query-Kontext veröffentlicht. Cesium-Darstellung, URL, CHRONIK,
Neo4j, Qdrant und Munin sind abgeleitete Adapter. Kamera, Selection, Spotlight,
Viewport und Render-LOD sind niemals semantische Source of Truth.

## Review-Status

Der adversariale Erst-Review vom 2026-08-01 setzte die Freigabe auf FAIL. Der Re-Review
bestätigte dessen acht Korrekturen und fand `WARN-007/008`; der Abschluss-Review
verifizierte auch diese Fixes und endete mit **PASS**, hoher Konfidenz und bestandenem
Security-Gate. Alle zehn Findings sind geschlossen. Dieser Spec-Satz ist die
freigegebene Implementierungsgrundlage für die TDD-Slices aus `13`.

Die am 2026-08-10 in ihren normativen Heimaten ergänzten Cinematic-Deltas ändern
diesen Core-Status nicht, sind selbst aber noch nicht aktiv: Zwei Review-Runden
endeten `PASS WITH REQUIRED FIXES`; beide Fix-Sätze sind eingearbeitet, ein
unabhängiger Abschluss-PASS steht aus. Sie autorisieren bis dahin weder Cinematic-
Code noch einen Implementierungsplan.

Protokollhinweise ohne aktuellen Blocker: `03` und `04` liegen nahe am Wortbudget;
ihre nächste inhaltliche Erweiterung erfordert die Seam-Prüfung aus dem
Änderungsprotokoll. Landen vor Slice 3 relevante Frontend-Änderungen, wird der in
`01 §3.1` dokumentierte Ist-Zustand kurz gegen den dann aktuellen Tree revalidiert.

## Teil-Specs

| Teil | Normativer Besitz | Aktueller Umfang inkl. Navigationskopf |
|---|---|---:|
| [01 — Architektur und Invarianten](2026-07-31-spatial-scope-drilldown/01-architecture-and-invariants.md) | Entscheidung, Ist-Zustand, Ziele, Begriffe, globale Trennlinien, Interface-Auswahl | 1.641 Wörter |
| [02 — Scope-Identität und Boundary-Policy](2026-07-31-spatial-scope-drilldown/02-scope-identity-and-boundary-policy.md) | Schlüsselgrammatik, Lineage, politische Representation, Katalog-/Derivationsrevision | 810 Wörter |
| [03 — Frontend-Core und Navigation](2026-07-31-spatial-scope-drilldown/03-frontend-core-and-navigation.md) | TypeScript-Interface, State Machine, Races, Lifecycle, React-Hook, URL/History | 1.953 Wörter |
| [04 — Spatial-Catalog-Verträge](2026-07-31-spatial-scope-drilldown/04-spatial-catalog-contracts.md) | Ownership, HTTP/Wire, Backend-Modelle, Frontend-Validator, Cache und Lifecycle | 1.968 Wörter |
| [05 — Boundary-Build und Antimeridian](2026-07-31-spatial-scope-drilldown/05-boundary-build-and-antimeridian.md) | Quellen, Source Lock, Offline-Build, Topologie, LOD, Budgets, Datumsgrenze | 1.450 Wörter |
| [06 — Cesium und Layer-Semantik](2026-07-31-spatial-scope-drilldown/06-cesium-and-layer-semantics.md) | Primitive-Lifecycle, Staging, Picking, Kamera, Prefetch, Layer-Capabilities | 1.701 Wörter |
| [07 — CHRONIK-Query-Vertrag](2026-07-31-spatial-scope-drilldown/07-chronik-query-contract.md) | Timeline-Request, Response-Accounting, statische Query-Compiler, stale UI | 920 Wörter |
| [08 — Neo4j-Normalisierung](2026-07-31-spatial-scope-drilldown/08-neo4j-normalization.md) | Location-Schema, Indizes, Writer, Konflikte, Backfill und Coverage-Gate | 655 Wörter |
| [09 — Qdrant-Retrieval](2026-07-31-spatial-scope-drilldown/09-qdrant-retrieval.md) | Payload-Schema, Indizes, Filter-Compiler und Partial Coverage | 792 Wörter |
| [10 — Munin Scope Enforcement](2026-07-31-spatial-scope-drilldown/10-munin-scope-enforcement.md) | Request, Run-Snapshot, ToolRuntime, Graph-Templates und Tool-Matrix | 1.293 Wörter |
| [11 — UX und 3D-Metriken](2026-07-31-spatial-scope-drilldown/11-ux-and-3d-metrics.md) | Breadcrumb, Click/Escape, Selection, stale Wahrheit, Attribution, spätere Extrusion | 1.228 Wörter |
| [12 — Fehler, Security und Observability](2026-07-31-spatial-scope-drilldown/12-errors-security-and-observability.md) | Fehlerklassen, Retry, Fail-closed, Missbrauchsschutz, Logs und Metriken | 699 Wörter |
| [13 — Umsetzung und TDD-Slices](2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md) | Dateiplan, neun vertikale Slices, Red Tests, Gates und Testkommandos | 1.813 Wörter |
| [14 — Rollout und Abnahme](2026-07-31-spatial-scope-drilldown/14-rollout-and-acceptance.md) | Kompatibilität, Rollback, Stop-Regeln, Alternativen, DoD und Primärquellen | 1.109 Wörter |

Keine Teil-Spec überschreitet 2.000 Wörter einschließlich ihres Navigationskopfs. Die
ursprünglichen Abschnittsnummern 1–30 bleiben stabil und jeder Abschnitt besitzt
genau eine normative Heimat.

## Selektive Review-Pfade

`01` ist die gemeinsame Architekturgrundlage; `02` wird geladen, sobald Scope-Key,
Lineage, Revision oder Boundary-Representation relevant sind. Danach genügt der
fachliche Pfad:

| Review | Dateien in Ladereihenfolge |
|---|---|
| Architekturentscheidung | Index → `01` → `02` → `14` |
| Frontend-State und URL | Index → `01` → `02` → `03` |
| Catalog-Backend | Index → `01` → `02` → `04` |
| Boundary-Datenpipeline | Index → `02` → `04` → `05` |
| Cesium-Rendering | Index → `01` → `03` → `04` → `06` |
| CHRONIK | Index → `02` → `04` → `07`; für exact zusätzlich `08` |
| Neo4j-Ingestion | Index → `02` → `04` → `08` |
| Qdrant | Index → `02` → `04` → `09` |
| Munin/LangGraph | Index → `02` → `08` → `09` → `10` |
| UX/3D-Metrik | Index → `01` → `03` → `06` → `11` |
| Security/Release | Index → `01` → `12` → `14` |
| Umsetzung eines Slice | Index → betroffene fachliche Teile → relevante Passage in `13` |
| Cinematic WorldView | Index → `01` → `03` → `04` → `06` → `11` → `12` → `14` → Cinematic-Spec |

`13` ist kein notwendiger Architektur-Review-Input. Es wird erst für Planung oder
Umsetzung geladen. Ebenso ist `14` für einen schmalen Implementierungsreview nur
nötig, wenn Rollout, Stop-Regeln oder Gesamt-Abnahme betroffen sind.

## Normative Präzedenz

1. Dieser Index besitzt nur Dokumentstruktur, Lesereihenfolge und Präzedenz; er
   dupliziert bewusst keine Detailverträge.
2. Die globalen Invarianten aus `01` begrenzen alle anderen Teile.
3. Identität, Lineage, Boundary-Policy und Revisionssemantik gehören ausschließlich
   `02` und dürfen in fachlichen Adaptern nicht neu definiert werden.
4. Jeder fachliche Teil besitzt seine dort benannten Interfaces und Implementationsregeln.
5. Der Dateiplan und die TDD-Slices in `13` referenzieren diese Verträge, überschreiben
   sie aber nicht.
6. Rollout- oder Kompatibilitätsregeln in `14` dürfen Fail-closed-, Security- oder
   Truthfulness-Invarianten aus `01`, `02` und `12` nicht abschwächen.
7. Eine reviewte Erweiterungs-Spec darf neue, in der Registry eingetragene Verträge
   besitzen. Änderungen an bestehenden globalen, Cesium-, UX-/Metrik- oder Rollout-
   Regeln landen weiterhin zuerst in `01`, `06`, `11` beziehungsweise `14`.

Bei einem echten Widerspruch wird nicht anhand der jüngsten Textstelle improvisiert:
der Review stoppt, und der normative Eigentümer wird geändert. Cross-Links sind
Abhängigkeiten, keine zweite Heimat derselben Regel.

### Registry gemeinsam verwendeter Verträge

| Vertrag | Einzige normative Heimat |
|---|---|
| Scope-Key-Grammatik, Kinds als Semantik, Revisionsmodell | `02` |
| TypeScript `ScopeKey`, `ScopeKind`, `SpatialQueryRef` | `03` / `spatial/contracts.ts` |
| Backend `SpatialScopeTokenV1`, Katalog-/Derivationstypen | `04` |
| `SpatialApplicationV1`, CHRONIK-Zählsemantik und unveränderte CHRONIK-Szenenprojektion | `07` |
| Qdrant-Payload und Filter-Compiler | `09` |
| `SpatialRunApplicationV1` | `10` |
| `SpatialPresentationPort`, `PresentationOutcome`, `ViewerSpatialCesiumRuntime`, `SceneStateLease`, `WorldviewPostProcessController`, `StrictPointLayerApplication<T>` | `06` |
| `WorldviewMotionSnapshot`, `WorldviewMotionStore`, `SpatialMetricId`, `SpatialMetricDefinition`, `SpatialMetricSample`, `SpatialMetricSnapshot`, `SpatialMetricPort` | `11` |
| `worldview_presentation_mode`, Shared-Refactor-Stufe und Operational-/Cinematic-Mode-Matrix | `14` |
| `CinematicWorldviewModule`, `WorldviewSceneFrame`, `WorldviewLensId`, `CinematicWorldviewDiagnostics` | [Cinematic WorldView](2026-08-10-cinematic-worldview-design.md), erst nach Abschluss-PASS aktiv |

Andere Teile importieren, verlinken oder zeigen nur Benutzung. Sie dürfen diese
Deklarationen nicht kopieren. Slice 0 besitzt ein Dokument-Gate für eindeutige
Contract-Owner.

## Änderungsprotokoll für Agents

1. Nur den Index und den passenden Review-Pfad laden.
2. Zuerst die normative Heimat der Änderung identifizieren.
3. Den Vertrag dort ändern; abhängige Teile nur anpassen, wenn sich deren Interface
   tatsächlich ändert.
4. Bei Verhaltensänderungen die passenden Red Tests/Gates in `13` aktualisieren.
5. Bei Deployment- oder Abnahmewirkung zusätzlich `14` aktualisieren.
6. Wortbudget prüfen. Wächst ein Teil über 2.000 Wörter, wird seine innere Seam erneut
   bewertet, statt den Monolithen schleichend wiederherzustellen.

## Präzedenz gegenüber älteren Specs

Nach Freigabe und Umsetzung ersetzt dieser Spec-Satz nur den Country-Zweig des
polymorphen Spotlight-Vertrags im
[WorldView Layer-Design](2026-04-30-worldview-layer-design.md). Circle-Spotlight und
das Hlíðskjalf-Designsystem bleiben bestehen. Er erweitert die Verträge aus
[Temporal Tracking](2026-06-01-temporal-tracking-design.md) und
[Timeline UX / CHRONIK](2026-06-09-timeline-ux-redesign-design.md) um semantischen
Raum und ersetzt ab Slice 7 die bewusst promptbasierte Regionseingrenzung des
[Country Briefing](2026-06-01-country-briefing-design.md). Das
[Hlíðskjalf Noir Design](2026-04-14-odin-4layer-hlidskjalf-design.md) bleibt die
visuelle Grundlage. Bis zum jeweiligen Slice gilt der implementierte Altvertrag.
