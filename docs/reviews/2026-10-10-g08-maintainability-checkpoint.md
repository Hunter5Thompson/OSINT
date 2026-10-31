# G08 — Wartbarkeit und geschützte Inventur

Sourceübernahme auf Basis `e8603c6`, jetzt scoped committet, einziger Servicewriter.
Keine Integrations-/Deployment-/Daten-/Löschfreigabe daraus ableiten.

`spatial/catalog.ts` wurde entlang bestehender Verantwortungen zerlegt:
core, metadata, geometry, assets, memory und http. Die39 Zeilen-Facade erhält
exakt28 öffentliche Exporte. WorldView-Schichtbrücken und Callbackbrücken sind
aus der Seite in zwei vorhandene Verantwortungsgrenzen ausgegliedert; die
Seite behält State und Orchestrierung. Kein neuer State-/Timer-/URLvertrag.

AST-Prüfung bestätigt alle116 Katalog- und25 WorldView-Deklarationsinhalte
unverändert, abgesehen vom nötigen Exportmodifier. Importauflösung und Verhalten:
Katalogfokus60, WorldViewfokus 20, vollständiger Frontendlauf132 Dateien/837 Tests,
ESLint, Repo-/Browser-TypeScript und Build grün. Buildrevision null beim dirty
Sourcebuild. Kein neuer finaler Head, Image- oder Browserpass.

TASKS enthält nun Statusmatrix, Betriebsstack und Taskverzeichnis. Vollständige
Briefings liegen einmalig in docs/tasks/specifications.md; frühere Ergebnisse
einmalig in docs/tasks/history-2026-10-10.md. architecture.md und decisions.md
sind maßgeblich; docs/-Pfade verweisen auf sie. Historische Beispielversionen
und frühere Checks werden nicht als aktueller Betriebsbeleg dargestellt.
Geschützte `.codex` nennt Fusion Core noch TASK-108; maßgeblich ist TASK-112 im
Registry. Diese read-only Agentenregeldatei wurde nicht verändert.

Frische readonly Inventur:18 registrierte Worktrees, nicht 17. Hauptcheckout
813594a/3Untracked und fremde7c190c0/18Dirty unverändert. Unbestätigte Besitzer,
Zwecke und aktuelle Live-Mounts bleiben UNKNOWN; alle Worktrees erhalten.
Größen betreffen tracked Quelldateien, keine Aussage über Cache-/Datendichte.
Frisches df: /data 2.3T frei33%, / 204G frei89%; keine Volumes verschoben.

Vor der Integration blieben fünf transitive NPM-Findings offen. Installierte
Versionen und ältere Auditantwort sind getrennt gesichert. Web-Advisories
bestätigen Patchkandidaten source-map-js 1.2.2, js-yaml 4.3.2, undici 7.29.1 und
DOMPurify 3.4.16. Cache enthält nur alte Tarballs; offline Probe ENOTCACHED.
Kein manuell erfundener Lockhash, kein auditfix oder ungeprüftes Majorupgrade.
Gezielter kompatibler Dependency-/Lockwechsel mit npmci, Tests und neuem Audit
war erforderlich, sobald normale zulässige Registryverbindung verfügbar ist.

## Reguläre Integration durch Writer01a12412-a9fe-7052-93e0-ba88db75c740

Die Registryverbindung funktioniert ohne Konfigurations-/Hookänderung. Gezielt
aktualisiert: brace-expansion (drei verschachtelte1.1.21 sowie5.0.12),
DOMPurify3.4.16, js-yaml4.3.2, source-map-js1.2.2 und undici7.30.0.
Acht Lockknoten ändern sich; Paketmanifest und sonstige Dependencybäume bleiben.
Frisches npmci und Audit0, ESLint/Repo-/Browsertypen sowie870Fulltests PASS.
Finaler Head/CI bleiben separat; keine auditfix-/Majoraktion.

Read-only-Abgleich10.10:18 Worktrees,15 laufende produktive Container mit
Mountquellen und Startzeiten; Maina47da45, PR138MERGED, kein GoalPR. Protected
813594a/3 und Spark7c190c0/18 erhalten. Keine fremde Eigentümerschaft aus
Branchnamen abgeleitet, keine Löschung/Volumeverschiebung. Aktuelle Rohbelege:
`evidence/integration-20261010/{worktree-runtime-inventory-0454.json,github-pr-inventory.json,dependency-lock-delta.json,dependency-audit-after.json}`
im externen Goalverzeichnis. Historische Quell-/ASTbelege bleiben erhalten.

Artefakte: `/data/odin-goals/2026-10-09-repo-hardening/evidence/G08/`:
declaration-move-proof.json, refactor-full/lint/build.log, unveränderte
Vorherdateien, Worktree-Inventur und Dependencycache-/Tree-/Auditbelege.
