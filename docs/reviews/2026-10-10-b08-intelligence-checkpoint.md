# B08 — lokaler Sourcecheckpoint, vollständiger Graphgate offen

L01: Baseline22, neun fachliche REDs (Teilwörter, zitierte Namen, leere und
unquoted Orts-/Entitätsphrasen), danach Fokus37 grün. Vollständige Wort-/
Phrasengrenzen, zitierte Namen für Routing maskiert, quoted Entity erhalten;
OPERATES/PROCURES weiter one_hop, kein freier Cypherpfad aktiviert.

L02: neun fachliche Node-REDs plus korrigierter ASGI-EndpointRED (initial falscher
Responsekey report war ein Testfehler; echter Vertrag analysis). Ein zusätzlicher
HIGH-RISK-Grenzfall RED, Parser korrigiert. Ein gemeinsamer deterministischer
Feldparser für beide Synthesen und Legacyanalyst: Markdown/Nummerierung,
Folgezeile, Duplikate, ungültige/missing Labels, Codeblöcke und Prosepositionen.
Fallback pro ungültigem Feld MODERATE/0.5 mit einmaligem neutralem Hinweis und
strukturiertem Issue-Log ohne Berichttext. Prompts auf denselben Feldvertrag.
Sources weiterhin ausschließlich aus gültigen strukturierten Artefakten.

L03: sieben fachliche REDs am tatsächlichen ToolNode mit synthetischen Providern
plus fünfter-Turn-RoutingRED. Vorschläge zählen nicht; jeder gestartete Aufruf
reserviert vor await seinen Slot, auch bei Fehler. Parallelbatch startet nur
den ersten zulässigen Anteil; Blockierte erhalten korrelierte error-ToolMessages
ohne Artifact/ausgeführten Trace. Nach fünftem Turn/finalem Slot Synthese statt
sechstem LLM; Guard zusätzlich direkt am LLM-Rand. Cancel propagiert, Provider
beendet, gestartete Anzahl diagnostiziert; kein resumierbarer Cancelpass behauptet.

Fokus130 grün, ein vollständiger fünfter-Turn-Graphfall ausdrücklich nicht
qualifiziert. Ruff und diff-check grün. Der vollständige Graph hängt im
Executor-Wakeup: erster Lauf68245 exit130 ohne abgeschlossene Failure-Zusammen-
fassung, korrigierter Boundarylauf7 echte Failures; weiterer begrenzter
Graphdiagnostic37051 mit6s Faulthandlerstack, SIGINT/Timeout konnte Shutdown nicht
beenden, eigener Toolprozess per Interrupt exit130 beendet. Kein Lib-/Thread-/
Policy-Patch. Dieser Fall bleibt im Testsatz, keine Skipmarkierung/Goldenlockerung.
Gesamt-Intelligencegate offen; keine unveränderte Fullsuite-Hangwiederholung.
Belege evidence/G04/B08; dirty Source e8603c6, kein Commit/PR/Image/Live-/Faktenpass.
