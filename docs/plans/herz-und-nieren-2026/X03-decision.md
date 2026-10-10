# X03 — mehrdeutige Scope-URL, Entscheidungsvorlage

Stand 10.10.2026; fachliche Entscheidung noch offen. Kein neuer URL-Vertrag ist
durch diese Vorlage freigegeben.

`navigation.ts` liest alle `scope`-Parameter. Mehr als einer wird als ungültiger
Kandidat weitergegeben, auch bei identischen Werten. Der Controller verwirft den
Kandidaten mit `INVALID_SCOPE_KEY`; initial kann er auf Welt zurückfallen,
Historynavigation repariert den letzten gültigen Scope. Das Problem ist im
Zustandsvertrag vorhanden. Eine mehrdeutige URL darf keine neue Länderabfrage
auslösen, und ihre erste oder letzte Komponente darf nicht still gewinnen.

Empfehlung: alle mehrfachen Parameter weiter ablehnen, einschließlich identischer
Duplikate. Einen verständlichen sichtbaren Hinweis anzeigen: „Mehrdeutige
Gebietsauswahl in der URL.“ Bei vorhandenem gültigen Scope dessen Ansicht
erhalten; ohne vorherige Auswahl eine klar als Rückfall bezeichnete Weltansicht
anzeigen. Der Nutzer kann über vorhandene Auswahlcontrols einen eindeutigen
Scope wählen. Backend- und Revisionsschutz bleiben erhalten.

Alternative: identische kanonische Duplikate erlauben, widersprüchliche ablehnen.
Das benötigt ausdrücklich eine Normalisierungsentscheidung samt URL-Reparatur;
Aliaspaare und unterschiedliche Katalogrevisionen dürfen dabei nicht implizit
gleichgesetzt werden. Kein first-wins oder last-wins.

Nach Entscheidung kleines UX-Ticket: `scope=UKR&scope=DEU`, identische Duplikate,
gültiger vorheriger Scope, initialer Deep-Link, Browser-Back/Forward und veraltete
Revision prüfen. Navigation→Controller→sichtbarer Hinweis testen; Requestspy
belegt keine ungesicherte Länderabfrage. Browsernachweis bleibt eigene Abnahme.
U08-SSE-Reset bleibt unabhängig von dieser Produktentscheidung.
