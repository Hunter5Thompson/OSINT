# Intelligence-Pakete

Gemeinsamer Vertrag: [README](README.md). Pfade relativ zu `services/intelligence`, außer L06.

## L01 — Intent anhand ganzer Ausdrücke routen

**F-10 Intentteil · P2 · S · nach S01.**

**Scope:** `agents/tools/graph_query.py::_match_intent`, `tests/test_graph_query.py`, `test_graph_query_operates_intent.py`, `test_graph_query_procures_intent.py`.

**RED:** `resources` darf nicht `source_backed` auslösen; `cooperate` nicht wegen `operate`; `events involving the 5th fleet` nicht als Ortsanfrage. `events in Black Sea` bleibt Ortsanfrage, quoted entity bleibt erhalten. Plurale, Satzzeichen und Groß/Kleinschreibung testen.

**GREEN:** priorisierte explizite Phrasen-/Wortgrenzen, konservativer Fallback bei fehlender Entität statt ganzer Fragesatz als Ort. Bestehendes bewusstes `operates/procures → one_hop` erhalten. Keine neue Relationsextraktion und kein neu freigeschalteter freier Cypher-Pfad. LIMIT wird in S01 unabhängig abgesichert.

## L02 — Assessment nur aus deklarierten Feldern lesen

**F-16 · P1 · M.**

**Scope:** `graph/workflow.py`, `graph/nodes.py`, neuer kleiner gemeinsamer Assessmentparser; `tests/test_workflow.py`, `test_synthesis_prompt.py`, `test_legacy_prompts.py` und neue parametrisierte Parsertests. Bestehende API-Felder bleiben kompatibel.

**Vertrag:** kurzfristig deterministischer Parser für explizite `Threat Assessment:`- und `Confidence Level:`-Felder, einschließlich tatsächlich erzeugter nummerierter Markdown-Überschriften und Wert in Folgezeile. Nur gültiges Label an der Feldposition, nicht beliebige Treffer im Bericht. Kein weiteres LLM zur Reparatur. Prompts auf denselben eindeutigen Vertrag bringen. Duplicate/widersprüchliche/fehlende Felder gelten als Parsefehler; bestehender kompatibler Fallback MODERATE/0.5 bleibt nur zusammen mit sichtbarer Diagnose erhalten, nicht als sicher extrahierter Wert. Dafür dem ausgegebenen Bericht einmalig den neutralen Hinweis „Assessment-Felder konnten nicht eindeutig gelesen werden; angezeigte Standardwerte sind keine extrahierte Bewertung.“ anfügen und strukturiert loggen. Kein neues API-Schema in diesem Patch. Langfristiges strukturiertes JSON ist ein separater API-Vertrag, nicht Voraussetzung für diesen Fix.

**RED:** MODERATE + highway; MODERATE + `(not critical)`; highlight ohne Feld; low confidence + verneintes high confidence im Fließtext; eindeutige HIGH/CRITICAL/ELEVATED/MODERATE-Felder; erlaubte Confidencewerte; doppelte Felder; Markdown/Nummerierung. Beide Workflow-Varianten nutzen denselben Parser.

**Abnahme:** Parser-/Workflow-/Prompttests mit Fake-LLM; mindestens ein Endpoint-/Response-Test für Diagnoseweitergabe. `sources_used` weiterhin ausschließlich aus validiertem EvidenceArtifact/strukturierter Grounding-Herkunft, niemals neu aus Berichttext ableiten.

## L03 — Toolbudget am Ausführungsrand durchsetzen

**F-17 · P1 · M.**

**Scope:** `agents/react_agent.py`, `graph/workflow.py`, `graph/state.py`; `tests/test_react_agent.py`, `test_workflow.py`, `test_tool_lineage_contract.py`, `test_workflow_sources.py`. Backend/Frontend-Trace-Typen nur bei bewusst additiver Statusprojektion.

**Fester Vertrag:** maximal 8 tatsächlich gestartete Toolcalls, maximal 5 LLM-Entscheidungsturns (aktuelle Defaults). Ein Toolfehler verbraucht seinen gestarteten Slot. Der fünfte Turn darf noch zulässige Tools abarbeiten, danach Synthese ohne sechsten ReAct-Aufruf. Bei vorgeschlagenem Batch größer als Restbudget deterministisch ersten zulässigen Anteil starten, übrige als budget-blocked beantworten; ToolMessage-ID-Zuordnung bleibt vollständig. Reservierung vor parallel gestarteten Calls, Abschlussstatus danach.

**Trace:** vorgeschlagen ≠ ausgeführt. Für diesen Patch nur tatsächlich gestartete Calls im bisherigen Trace; blockierte Calls erhalten ihre korrelierte ToolMessage und Budgetdiagnose, erscheinen aber nicht als ausgeführter Trace-Eintrag. Kein neues Trace-Statusschema in diesem Paket. Kein `>=`→`>`-Einzeiler: der lässt große Batches überziehen.

**RED/Abnahme:** bisherige Anzahl 7 + Batch 1 → ein Tool läuft; 7+Batch 3 → genau eines; 8+Batch 1 → keines; Iteration 4 → fünfter Turn+Tools, dann Synthese; Toolfehler, parallel geschedulter Batch und Abbruch. Mocktools zählen tatsächliche Starts, ToolMessage-IDs und Artifact-Herkunft prüfen. Kein Live-LLM benötigt, Evidence-/Scope-Tests erhalten.

## L04 — RAG-Poison-Hits und nichtendliche Scores isolieren

**F-18 · P1 · S/M.**

**Scope:** `rag/corpus_policy.py`, `rag/content_quality.py`, `agents/tools/qdrant_search.py`; `tests/test_corpus_policy.py`, `test_qdrant_search_tool.py`, Evidence-/Provenienztests.

**RED:** Scoreliste 0.12/NaN/0.92, ±Infinity, bool/falscher Scoretyp; `content` als Liste/null zwischen zwei guten Treffern. Gesunder bester Treffer bleibt vorne, ungültiger Treffer verschwindet mit Diagnose. Bei ausschließlich ungültigen Treffern deterministische leere/diagnostizierte Antwort, keine erfundene Evidenz. Echter DB-/Retrieverfehler bleibt Fehler.

**GREEN:** Typ und Endlichkeit vor Boost/Sortierung prüfen; nichtendliche finale Scores ebenfalls ausschließen. Textqualität pro Hit nur auf Strings anwenden. Artefakt enthält exakt die gültigen, budgetgerecht tatsächlich gerenderten Treffer; keine Quellen aus verworfenen Hits. Keine Score=0-Ersetzung, die defekte Evidenz weiter transportiert.

## L05 — Chunkerparameter vor Schleife validieren

**F-19 · P2 · S.** `rag/chunker.py`, neue `tests/test_chunker.py`, vorhandene Indexertests.

**RED:** `chunk_size <= 0`, `overlap < 0`, `overlap >= chunk_size` ergeben sofort ValueError; bool/falsche Typen bewusst zurückweisen. Leer-/Whitespace-Text ergibt `[]`; Text genau Chunkgröße und normale 512/50 bleiben korrekt. Fortschritt/Terminierung bei Grenzwerten testen, ohne eine Endlosschleife ungebremst im Testprozess auszuführen (Prozess-Timeout für RED oder isolierte Parametervalidierung).

**GREEN:** Validierung vor Early Return, damit ungültige Parameter auch bei kurzem/leeren Text nicht akzeptiert werden. Keine neue Chunkingbibliothek; Indexer darf bei null Chunks keine leere Einbettung schreiben. Vorhandene normale Chunkfolge nicht unnötig ändern.

## L06 — Bericht-Bullets und Überschriften präzise parsen

**F-35 Berichtteil · P2 · S.** Backend `app/services/briefing.py`, `tests/test_briefing_context.py`, `test_briefing_save.py` und dortige Parser-Testanker.

**RED:** `- -12C` bleibt Inhalt `-12C`; `1. Bridge destroyed` und `1) ...` erhalten; `*`/`•` weiterhin gültig; bloß ähnliche Überschrift wird nicht als gewünschte Section erkannt. Vorhandene deutsch/englische Überschriftaliasse erhalten.

**GREEN:** genau einen syntaktischen Listenmarker per verankertem Muster entfernen, kein Zeichenmengen-`lstrip`. Normalisierte vollständige Überschriften über explizite Aliasliste zuordnen. Fallback bei unbekanntem Layout konservativ mit Originaltext erhalten. Keine Zeitparseränderung hier, die gehört zu I06.
