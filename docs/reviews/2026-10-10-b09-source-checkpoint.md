# B09 — Sourcecheckpoint; Runtime-/Graph-/Releasegates offen

S04: Baseline17 nach offline locked/all-extras Sync (vorher fehlte die Vision-
Testumgebung; erster Aufruf war kein Testlauf). Fünf Schema-/Retry-REDs, danach
36 Full-Service-GREEN; zwei weitere Partial-Persistence-REDs, final39 Full-GREEN.
Flag nur nach real validiertem Schema, Missingcollection/Timeout kein Erfolg,
Preflight vor Analyse und allen Persistenzwrites. Begrenzter Retry/DLQ bleibt.
Neo4j bestätigt genau einen Documentwrite; fehlender Qdranttarget/Writefehler
publiziert kein enriched-Erfolg/Erfolgs-ACK. Fakes liefern jetzt echte Schema-
objekte und explizite Neo4j-Countresponses, Fehlerasserts unverändert. Kein
Atomicityversprechen über beide Stores: ein erster Storewrite kann vor dem
späteren Fehler persistiert sein und wird beim Retry idempotent wiederholt.
Neuer Neo4j RETURNcount-Vertrag ist nicht gegen den realen Server geprüft.

L04: Baseline58 mit Chunker-Nachbar;13 Poison-REDs/1 bereits grün. Per-Hit-
Typ/Endlichkeitsprüfung vor Norm/Boost/Sort; ungültige finale Scores und Texttypen
fallen diagnostiziert heraus, gesunder bester Treffer bleibt. Keine 0-Ersetzung.
Zwei weitere REDs für sichtbaren Partial-/NoValidHits-Status; Callbackverluste
bleiben pro Request sichtbar. Evidencekonversion per Hit isoliert, Artifact nur
für tatsächlich budgetiert gerenderte gültige Treffer; Infrastrukturfehler
weiter failed/unknown, keine künstlichen Quellen. Contentquality-Twins unverändert:
Stringguard im Aufrufer, keine ungleich geänderte Kopie.

L05:14 fachliche REDs/2 normale Nachbarn grün; alle ungültigen Parameter zuerst
am leeren Text geprüft, keine ungebremste Baseline-Endlosschleife. Integer/nonbool,
size>0,0<=overlap<size vor Early Return; Whitespace→[], normale512/50-Folge erhalten.
Indexer ohne Chunks macht weder Collection- noch Embedding-/Upsertarbeit.
Gemeinsamer Intelligencefokus114 grün; Ruff für geänderte Module/Tests und
Diffcheck grün. Voll-Intelligence-/fünfter-Graphgate bleibt policyblockiert
(B08), keine unveränderte Hangsuite wiederholt. Vision39 Full-PASS ist eigener
Servicebeleg, kein Intelligence-/DB-/Image-/Deployment-/Faktenpass. Belege G04/B09.
