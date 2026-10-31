# G02 — Eindeutige Image-Buildquelle

Der neue lokale Build-Einstieg liest den vollständigen SHA aus einem sauberen
Gitstand und exportiert ausschließlich diesen Commit als Docker-TAR-Kontext.
Manuelle Revisionswerte und Dirty-Overrides sind nicht vorgesehen. Alle fünf
Appkontexte und das Spatial-Buildflag entsprechen dem vorhandenen CI-Vertrag.
Receipts unterscheiden lokale Image-ID und Kontext-Hash von Manifestdigest,
Smoke, Release und geladener Revision.

TDD: acht fehlende Featurefälle RED, danach acht GREEN. Zwei zusätzliche
Schutzfälle (Artefakte außerhalb Checkout und Headwechsel) ergänzen den Lauf:
elf PASS einschließlich abgewiesener Git-Override-Umgebung. Ruff grün. Der echte Planaufruf im eigenen dirty Worktree wurde vor
jedem Dockeraufruf abgewiesen. Keine Image-/Daemon-/Runtimewiederholung.
Prozessgrenzentests verwenden explizite Git-/Dockerantwortfixtures; tatsächlicher
Build/Smoke auf finalem sauberem Head bleibt offen. Bestehende Kontexte/Receipts
werden nicht überschrieben; Abbruch hinterlässt nur eigene neue Prüfarbeitsdateien.

Belege: Goal/evidence/G02/{red-build-release,green-build-release,
build-release-contract-final,build-release-ruff,build-plan-dirty-rejection}.log.
Der alte SHA3234993-Build bleibt unverwendbar. Gitindex/Remote/Dockerpolicy,
fehlende finale CI-/Manifest-/Live-/Rolloutfreigaben unverändert.
