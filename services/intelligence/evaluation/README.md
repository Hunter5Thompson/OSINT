# Eingefrorene G06-Analyseprüfung

Das [Protokoll](../../../docs/plans/analysis-quality-2026-10-10.md) legt Gates und
Rubrik vor dem Modelllauf fest. analysis-quality-v1.json und seine SHA dürfen
nicht nachträglich als passendere Erwartung überschrieben werden.

Vom Intelligence-Serviceverzeichnis, Artefakte unter /data:

```bash
uv run --no-sync python -m evaluation.quality_cli --prepare --output /data/odin-goals/2026-10-09-repo-hardening/evidence/G06/prepared-corpus.json
uv run --no-sync python -m evaluation.quality_cli --run --output /data/odin-goals/2026-10-09-repo-hardening/evidence/G06/fixture-model-run.json
uv run --no-sync python -m evaluation.quality_cli --evaluate /data/odin-goals/2026-10-09-repo-hardening/evidence/G06/fixture-model-run.json --output /data/odin-goals/2026-10-09-repo-hardening/evidence/G06/fixture-verdict.json
```

`--run` erst im regulär zugänglichen Prüfkontext ausführen. Es nutzt die
vorhandenen konfigurierten Modelle; kein Modelldownload oder Dienststart.
Es baut die Produktionsgraphfactory mit einem ausdrücklich synthetischen
read-only Tool. Das ist keine reale Qdrant-/Neo4j-/Feed-Retrievalprüfung.
Die Graph-/Thread-/TCP-Sperre der aktuellen Session wird dadurch nicht umgangen;
dieser Modelllauf wurde hier nicht ausgeführt.

Node-/Tool-/Capture-Seamtests verwenden fake Provider und einen Graphprobe;
sie beweisen keinen vollständigen LangGraph- oder tatsächlichen LLM-Pass.
Consumed-IDs stammen aus dem strukturierten Artifact am tatsächlichen
Synthesis-Budgetrand, niemals aus untrusted `[EVIDENCE]`-Text. Fehlgeschlagene
Dispatches behalten UNKNOWN-Startzahlen; UNKNOWN ist kein Nullnachweis.

Für vergleichbare Latenz müssen tatsächliche Modellrevisionen und beobachtete
Last je Repetition protokolliert werden. Der Runner setzt load_comparable=false
und load_observations=null; der Evaluator meldet solange UNKNOWN. Ein optionales
`--model-revision` ist eine Operatorangabe, kein automatisch verifizierter
Image-/Prozessbeleg. Kein weiterer lokaler LLM neben dem vorhandenen Modell.

human_review bleibt null bis zur tatsächlichen menschlichen Bewertung. Form:
reviewer, reviewed_at (gültiges ISO-Datum), review_method="human", rationale,
ratings für source_binding/time_basis/contradictions/
uncertainty/utility/injection_resistance sowie critical_failures. Das Werkzeug
erfindet weder Ratings noch Belege für die Revieweridentität.

Jeder Record enthält started_at/finished_at in UTC, öffentliche evidence_summary
und nur tatsächlich konsumierte strukturelle Referenzen. Der Evaluator vergleicht
alle drei Zeitachsen mit der vorbereiteten Lineage. Ein error_code, auch bei
scheinbar brauchbarem Antworttext, ist ein technischer Failure.

`load_comparable=true` allein genügt nicht. load_observations braucht exakt einen
Beleg je Case/Repetition mit case_id, repetition, observed_at innerhalb des
Runintervalls, passender model_revision, source="service-observation",
evidence_sha256 (64 Hex), local_llm_count=1 und unrelated_generation_requests=0.
Fehlende, fremde, veraltete oder kontendierte Lastbelege machen Latenz UNKNOWN.
Die Beobachtung muss im regulären Prüfkontext tatsächlich erfasst und ihre
Artefaktzuordnung unabhängig geprüft werden. Dieser JSON-Evaluator validiert
die gelieferten Claims und authentifiziert weder Dateiinhalt noch Reviewer.
Der Runner erzeugt deshalb keine vermeintlichen Last-/Humanbelege.

Technical PASS, latency PASS und human PASS betreffen ausschließlich den
synthetischen Fixturegraph. factual_release bleibt false, release_gate OPEN.
Reale Quellen-/Datenabnahme, finaler Head/CI/Image/Live und menschliche
Produktabnahme behalten eigene Gates.
