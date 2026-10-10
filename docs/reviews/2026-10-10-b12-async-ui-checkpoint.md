# B12 — lokaler Sourcecheckpoint, 10.10.2026

Basis `e8603c6b09ef81db892831dc1eca155d088c7e72`, einzige aktive Schreibsession
im Goalworktree. Kein Commit, PR, Image, Deployment oder historischer Datenwrite.

- U06: HTTP-boundary-Matrix aller sieben Hooks, 31 echte REDs/8 Passes vor dem
  Fix. Sechs Hooks erhalten lokale Effectgeneration, Requestsequenz und Abort;
  vorhandener Satellitenhook blieb unverändert. Pollfrequenzen, Parameter und
  Stale-on-error-Verträge bleiben erhalten. Disable, Reenable, Parameterwechsel,
  Unmount und alte Error/finally nach neuerem Start/Erfolg geprüft. Matrix nun
  46 grüne Fälle; nur die aktuelle Antwort setzt Daten/Ladezustand/Aktualisierungszeit.
- U07a: zwei echte REDs/4 Passes; Detail beim ID-Wechsel gelöscht und bereits beim
  Render nach ID gefiltert. Deselektion/Unmount invalidiert Sequenz, Fehler zeigt
  neutralen ID-Fallback und einen Hinweis. Kein alter Inspectorinhalt unter neuer ID.
- U07b: 11 echte Backend-REDs. Optionaler Titel durch alle vier Geo-Queryprojektionen,
  Modell/ASGI-API und öffentliche Frontendtypen bis zum Pinadapter. Fehlender Titel
  bleibt kompatibel; technische Typ-/IDlabels bleiben neutral. Der erste Frontend-
  RED war wegen überholter Einmal-Fixture nicht qualifiziert. Korrigierte stabile
  Fixture mit ursprünglicher Mappingformel reproduziert echten Titelverlust:
  `military.airstrike` statt `Original source headline`. Produktionsadapter korrigiert.
  53 Backend-/Spatialnachbarn grün. Tatsächlicher synthetischer ASGI-Wirebody durch
  Produktionsadapter in Node gelesen; Titel, Koordinaten und Spatialaccounting erhalten.
- U08: fünf echte REDs/1 Pass. Resetgeneration und begrenzter Livebuffer, Merge/Dedupe
  nach unveränderter kanonischer Server-ID, Cap6 und monotoner Cursor gemeinsam
  publiziert. Resetfehler erhält brauchbare Anzeige plus Live-Ereignisse; spätere
  Generation gewinnt. Geschlossene EventSource-Callbacks ignoriert, benannte
  Registrierungen beim Reconnect erhalten. Keine Änderung am URL-Scope-Vertrag.

Finale Frontendchecks: 132 Dateien/837 Tests, ESLint, Repo-/Browser-TypeScript und
Build grün. Backend Ruff/Mypy95 und Diffcheck grün. Rohbelege und Wireprobe unter
`/data/odin-goals/2026-10-09-repo-hardening/evidence/G04/B12`.
Korrektur der Testtypen und zwei Ruff-Zeilenverletzungen separat vor finalem Grün.

X03 liegt als [Entscheidungsvorlage](../plans/herz-und-nieren-2026/X03-decision.md)
vor; Nutzerfrage gestellt, Antwort ausstehend. Bestehende Duplikatablehnung bleibt.
Frontend-/Backendgesamt-, echte DB-, Built-Browser-, native GPU-, Human- und
Releasegates werden getrennt geführt. Backend-Gesamtprüfung ist weiterhin an
der bekannten Executorwakeup-Policy blockiert; kein Skip/Fixturepatch/Bypass.
