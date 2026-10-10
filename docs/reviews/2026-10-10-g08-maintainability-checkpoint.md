# G08 — Wartbarkeit und geschützte Inventur

Lokaler dirty Sourcecheckpoint auf Basis `e8603c6`, einziger Servicewriter.
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

Fünf bestehende transitive NPM-Findings bleiben offen. Aktuelle installierte
Versionen und ältere Auditantwort sind getrennt gesichert. Web-Advisories
bestätigen Patchkandidaten source-map-js 1.2.2, js-yaml 4.3.2, undici 7.29.1 und
DOMPurify 3.4.16. Cache enthält nur alte Tarballs; offline Probe ENOTCACHED.
Kein manuell erfundener Lockhash, kein auditfix oder ungeprüftes Majorupgrade.
Gezielter kompatibler Dependency-/Lockwechsel mit npmci, Tests und neuem Audit
bleibt erforderlich, sobald normale zulässige Registryverbindung verfügbar ist.

Artefakte: `/data/odin-goals/2026-10-09-repo-hardening/evidence/G08/`:
declaration-move-proof.json, refactor-full/lint/build.log, unveränderte
Vorherdateien, Worktree-Inventur und Dependencycache-/Tree-/Auditbelege.
