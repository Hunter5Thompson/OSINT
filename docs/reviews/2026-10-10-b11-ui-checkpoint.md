# B11 — lokaler Sourcecheckpoint, 10.10.2026

Basis ist `e8603c6b09ef81db892831dc1eca155d088c7e72` im einzigen Writerworktree
`/data/odin-worktrees/goal-release`. Änderungen sind uncommitted; der Gitindex
ist schreibgeschützt. Dieser Bericht bestätigt keinen PR, Release oder Livebetrieb.

U01 normalisiert Trackinterpolation auf den kurzen Longitudebogen und erhält
exakte Endpunkte. Flugspuren verwenden die vorhandenen Grad-ViewBounds samt
Antimeridianlogik. U02 behält polwärts 85° die originale Weltposition und spreizt
Stapel über begrenzte Pixeloffsets. Auswahldaten behalten Originalkoordinaten;
niedrige Breiten behalten die bisherige Darstellung.

U03 verwendet angeforderte Bucketzahl und Histogrammspanne für die Schrittweite,
danach wird auf das Replayfenster geklemmt. Anzahl belegter Bins und schmale Brush
ändern das Zeitraster nicht. Der gelesene Backendvertrag normalisiert gültige
Bucketzahlen nicht; die additive optionale Gridspanne erhält bestehende Aufrufer.

U04 ignoriert unmarkierte dekorative Picks. Bekannte Detaildaten und explizite
interaktive Tags behalten Vorrang; sechs callbackgesteuerte Layer erhalten Tags,
einschließlich ihrer tatsächlich interaktiven MilAircraft-Spuren. UI-/Spatial-/
Revision-/Terrainprioritäten und Drillpickcap bleiben erhalten. Verzögerte Klick-
und Hovercallbacks greifen nach Viewerzerstörung nicht auf die Scene zu.

Nach korrigierten Fixtures: 15 fachliche REDs für Geometrie/Raster/Picks;
fünf zusätzliche echte fehlende Interaktivtag-REDs und ein Destroycallback-RED.
Der erste Flight-Test fehlte im Scene-Stub an `frameState`, der erste EONET-Test
benötigte eine im Canvas-Stub nicht vorhandene Zeichenfunktion. Diese Setupfehler
sind keine fachlichen REDs. Der erste Volltest fand zwei echte verschachtelte
Billboard-ID-Tagprobleme, die im Resolver korrigiert wurden.

Final: 130 Testdateien / 781 Tests grün; ESLint, Repo- und Browser-TypeScript,
Produktionsbuild und `git diff --check` grün. Belege unter
`/data/odin-goals/2026-10-09-repo-hardening/evidence/G04/B11`.
Der dirty Sourcebuild hat keine committed Release-Revision.

Browserausführung bleibt an der bereits belegten TCP/Preview-EPERM-Sperre offen;
Datumsgrenzen-/Polarbild, native GPU, Route-Remount im gebauten Browser und
menschliche Bedienabnahme sind damit nicht nachgewiesen. Kein Policybypass oder
Wiederlauf unveränderter blockierter Prüfungen. Nächster unabhängiger Slice: B12.
