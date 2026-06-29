# Local Sovereign Agent Sidecar — Design / Idee-Capture

> **Status:** IDEE / Exploration — *nicht* terminiert, kein Code. Festgehalten am 2026-06-18,
> damit die Gedanken nicht verfliegen. Aufgreifen „wenn mal Zeit ist".
> **Registry:** TASKS.md → TASK-115 (Pointer auf dieses Dokument).
> **Verwandt:** `reference_ds4_dwarfstar.md`, `project_spark_ingestion_offload.md`,
> `reference_dgx_spark.md`, Spec `2026-04-14-spark-ingestion-wiring-design.md`.

---

## 1. Die Idee in einem Satz

Einen **zweiten, vollständig lokalen Agenten neben Claude Code laufen lassen** — angetrieben von
**DeepSeek V4 Flash**, ausgeführt über die **ds4 / DwarfStar4** Inference-Engine auf der **DGX Spark**.
Der Reiz ist nicht „Ersatz für Claude", sondern der **Cloud/Lokal-Split**: ich (Claude Code) laufe
durch Anthropics Cloud (schnell, frontier, aber Daten verlassen die Box); der lokale Agent bleibt
**souverän, offline, kostenlos** auf eigener Hardware.

**Explizit NICHT das Ziel:** kein Ingestion-/Extraction-Tool. Der Write-Path (Feed → JSON → Pydantic
→ deterministische Cypher-Templates → Neo4j) bleibt deterministisch und single-shot. Ein agentischer,
self-improving Harness gehört dort *nicht* hin (würde Reproduzierbarkeit + Write-Path-Disziplin
untergraben). Siehe Abgrenzung §3.

---

## 2. Motivation — warum das für ODIN Sinn ergibt

1. **Datensouveränität (der eigentliche Grund).** ODIN ist eine OSINT-/Intelligence-Plattform.
   Sensible Quellen, vertrauliches Material, Dinge die man bewusst *nicht* an eine US-Cloud-API
   schicken will — die darf ein lokaler Agent verarbeiten, ich nicht. „Bleibt auf der Box" ist hier
   ein hartes Feature, kein Nice-to-have.
2. **Null Token-Kosten.** High-Volume-Grunt-Work und Dauerläufer ohne Zähler im Blick. (Vgl.
   `feedback_token_frugal_reviews` — Kostenbewusstsein ist etabliert.) Lokaler Agent = nach Strom gratis.
3. **Offline-Resilienz.** Funktioniert ohne Internet.
4. **Der „(leider)"-Punkt umgedreht:** Dass ich Cloud bin und der Lokale lokal, ist kein Trostpreis,
   sondern *die* Architektur — zwei Werkzeuge mit je eigenem Sweet Spot, kein Kompromiss.

---

## 3. Die drei Schichten (Orthogonalität — wichtig)

| Schicht | Komponente | Was sie liefert |
|---|---|---|
| **Inference-Engine** | ds4 / DwarfStar4 | *wie* das Modell läuft (Speed, KV-Cache, SSD-Streaming) |
| **Modell** | DeepSeek V4 Flash q2 | rohe Fähigkeit *pro Token* |
| **Harness** | ds4-agent / Claude Code / Hermes | *wie* die Fähigkeit eingesetzt wird (Tools, Multi-Turn, Memory) |

Ein Harness macht das Modell **nicht klüger pro Token** — er gibt ihm Werkzeuge, mehrere Runden,
Feedback, Gedächtnis. Andere Stellschraube als „besseres Modell".

**Abgrenzung Ingestion vs. Read/Agent:**
- **Write-Path (Ingestion):** deterministisch, schema-gebunden, single-shot. Harness = falsches
  Werkzeug. Was dort hilft, ist höchstens ein *dünner deterministischer Loop* (Retry bei
  Pydantic-Fehler, optionaler Verify-Call) — kein self-improving Agent.
- **Read-/Agent-Path:** offen, mehrstufig, tool-nutzend. *Hier* glänzt ein Agent. Aber: es existiert
  bereits ein domänenspezifischer **LangGraph-ReAct-Agent** (intelligence service: qdrant_search,
  graph_query, gdelt, synthesis). Ein lokaler Agent ist also „neben/ergänzend", nicht „ersetzt Ingestion".

---

## 4. Komponenten konkret

### 4.1 ds4 / DwarfStar4 (Inference-Engine)
- antirez (Redis-Schöpfer), Open Source (MIT, GGML-Teile beibehalten), **Beta** (Stand Juni 2026,
  „months to stable" laut README), ~14.5k ⭐. Mostly C/CUDA/Metal, reimplementiert GGML-Quant-Kernels.
- **Nur** DeepSeek V4 Flash / PRO — kein generischer GGUF-Runner. Bewusst „vertikal perfekt für ein Modell".
- Repo: https://github.com/antirez/ds4 · Blog: https://antirez.com/news/165
- Server `ds4-server` exponiert: **Anthropic** `/v1/messages` (tool_use), **OpenAI** `/v1/chat/completions`
  + `/v1/responses` (Codex), Legacy. Disk-KV-Persistenz (SHA1-keyed), SSD-Streaming, distributed.
- Build-Target für unsere HW: `make cuda-spark` (GB10), `CUDA_ARCH=sm_120` (Blackwell/5090, falls je relevant).

### 4.2 DeepSeek V4 Flash q2 (Modell)
- 284B MoE, asymmetrische Quant: routed Experts 2-bit (IQ2_XXS/Q2_K), Router/Attention/shared = Q8/F16.
- **q2 = 80.8 GB** → passt in Spark-128GB unified mit Platz für ~100k-ctx KV.
- **q4 = 153.3 GB → passt NICHT in 128 GB.** Auf der Spark also q2-only (außer distributed/SSD).
- Weights: https://huggingface.co/antirez/deepseek-v4-gguf · `./download_model.sh q2-imatrix`
- Qualität: antirez „a lot more B than A" (frontier-nah, nicht frontier).

### 4.3 Harness-Optionen (Entscheidung offen — §8)
- **(a) ds4-agent (nativ):** kein Extra-Teil, natives DSML-Tool-Calling, persistente On-Disk-Sessions.
  Aber **alpha**, simpel.
- **(b) Claude Code → lokales Hirn:** ds4-README liefert Wrapper-Script (`ANTHROPIC_BASE_URL` auf Spark).
  Ergebnis: *„Claude Code mit lokalem DeepSeek-Hirn"* — vertrautes Harness, lokales Modell. **Schnellster
  Beweis, geringste Lernkurve.**
- **(c) Hermes Agent (NousResearch):** reichster Loop — self-improving Skills, persistente Memory,
  Telegram/Discord-Gateways (Telegram nutzen wir eh), agentskills.io-Standard. Hängt sich an ds4s
  OpenAI-Endpoint. ~v0.9 (April 2026), ~27k ⭐. Repo: https://github.com/nousresearch/hermes-agent
  ⚠ self-improving + Memory = Non-Determinismus; nur für Read/Assistant-Seite, nie Write-Path.

### 4.4 Omnigent (spätere Koordinationsschicht — optional)
Echte *koordinierte* Zusammenarbeit (ich delegiere an den Lokalen / er reviewt mich) ist die Rolle eines
**Meta-Harness**. Der volle Stack wäre:
**ds4 (lokales Hirn) ← Hermes/Claude Code (Harness) ← Omnigent (Komposition + stateful Policies/Leine).**
Omnigent = Databricks, Apache 2.0, Alpha. Genau dessen Policies (ALLOW/ASK/DENY, Cost-Budgets) sind das,
was ein self-improving lokaler Agent zum sicheren Betrieb bräuchte.
Repo: https://github.com/omnigent-ai/omnigent · Blog: databricks.com/blog/introducing-omnigent-...
**Für Start NICHT nötig** — zwei getrennte Sessions/Prozesse reichen erstmal (manuell gefahren).

---

## 5. Hardware / Placement

- **DGX Spark GB10, 128 GB unified (@ 192.168.178.39) = DIE Box.** Dedizierter `make cuda-spark`-Build,
  antirez benchmarkt GB10 selbst: q2 @ 7047 tok → **343.8 t/s prefill, 13.75 t/s generation**.
- **RTX 5090 (32 GB) ist KEIN Target.** 80-GB-Modell wäre SSD-streaming-bound und unbrauchbar langsam.
  Die 5090 bleibt auf ihren AWQ/GGUF-Modellen.

---

## 6. ⚠ Der Ressourcen-Konflikt (kritisch, leicht zu übersehen)

DeepSeek V4 q2 belegt **80.8 GB resident** auf der Spark. Der bestehende
**Spark-Ingestion-Offload-Plan** (`project_spark_ingestion_offload`) will *dieselbe* Box nutzen, um
Ingestion-LLM + TEI dort hinzulegen und den GPU-Swap der 5090 zu eliminieren.

→ Läuft der lokale Agent dauerhaft mit 80 GB, ist der Swap **nicht eliminiert, nur von der 5090 auf die
Spark verschoben.** Drei Auswege:
- **(a) On-Demand:** Agent nur bei Bedarf hochfahren; Ingestion-Modell bleibt Default-Resident.
- **(b) Spark = Agent-Box:** Ingestion bleibt/swappt auf der 5090.
- **(c) Mehr Hardware.**

Diese Entscheidung muss *zusammen* mit dem Ingestion-Offload-Plan getroffen werden, nicht isoliert.

---

## 7. Arbeitsteilung (so ist es gedacht)

| | **Ich (Claude Code, Cloud)** | **Lokaler DeepSeek-Agent (Spark)** |
|---|---|---|
| Speed | schnell | ~13.75 t/s — zäh |
| Fähigkeit | Frontier | stark, aber „B nicht A" (q2/2-bit) |
| Daten | verlassen die Box | bleiben lokal |
| Kosten | Token | Strom |
| Sweet Spot | schnelle Iteration, harte Reasoning-/Coding-Tasks, unkritische Daten | privacy-sensibles Wühlen im Korpus, kostenlose Massen-Grunt-Work, langsame Hintergrund-Jobs, Offline-Fallback |

---

## 8. Offene Entscheidungen (zu klären, wenn aufgegriffen)

1. **Welcher Harness?** (a) ds4-agent nativ · (b) Claude-Code-mit-lokalem-Hirn (empfohlen für ersten
   Beweis) · (c) Hermes (eigenständiger self-improving Assistent mit Memory + Telegram).
2. **Placement-Modus?** On-Demand vs. dedizierte Agent-Box (§6) — hängt am Ingestion-Offload-Plan.
3. **q2-only akzeptabel?** Für die meisten Agent-Tasks ja; falls Spitzenqualität nötig → distributed/SSD (langsamer).
4. **Omnigent jetzt oder später?** Start: zwei getrennte Sessions. Koordination/Policies später.

---

## 9. Throughput-Realität (Erwartungsmanagement)

Agentic = **viele** Modell-Calls pro Aufgabe (Hermes triggert Skill-Generierung erst nach 5+ Tool-Calls).
Bei 13.75 t/s multipliziert ein Agent-Loop diese Langsamkeit über zig Turns. Lokal + privat **ja**, aber
für schnelle interaktive Iteration **zäh**. Die Spark ist die bessere *Batch-/Hintergrund-Agent*-Box als
interaktive Live-Coding-Box. Nicht als „schnelleres Claude" erwarten.

---

## 10. Konkreter erster Schritt (billigster Beweis)

**Weg (b) — Claude Code mit lokalem Hirn:**
1. Auf der Spark (.39): `make cuda-spark`
2. `./download_model.sh q2-imatrix` (80.8 GB)
3. `./ds4-server --ctx 100000 --kv-disk-dir /var/ds4-kv --kv-disk-space-mb 8192` (ggf. `--host 0.0.0.0`)
4. Claude-Code-Wrapper: `ANTHROPIC_BASE_URL=http://192.168.178.39:8000`, `ANTHROPIC_MODEL=deepseek-v4-flash`
5. *Fühlen*: wie verhält sich „lokaler Zwilling" bei einer echten ODIN-Aufgabe? t/s mitnehmen.

Damit kein neuer Harness gelernt werden muss und man sofort den Cloud/Lokal-Kontrast erlebt. Erst wenn
sich das lohnt: Hermes (eigenständiger Assistent) und/oder Omnigent (Koordination) evaluieren.

---

## 11. Risiken / Vorbehalte

- **ds4 Beta, Hermes ~v0.9, Omnigent Alpha** — alle jung, Churn, Wartungslast.
- **Single-Model-Lock-in auf bewegliches Ziel** — antirez nennt die Modellwahl „opportunistic".
- **q2 / 2-bit** — gut abgesichert (asymmetrisch + offizielle Logit-Vektoren), aber bleibt 2-bit.
- **Spark-Ressourcenkonflikt** (§6) — der größte praktische Stolperstein.
- **DeepSeek = CN-Modell** — aber lokal/offline, verlässt die Box nicht → Governance-Punkt entschärft.

---

## 12. Quellen

- ds4: https://github.com/antirez/ds4 · https://antirez.com/news/165 · https://huggingface.co/antirez/deepseek-v4-gguf
- Hermes: https://github.com/nousresearch/hermes-agent · https://hermes-agent.nousresearch.com/
- Omnigent: https://github.com/omnigent-ai/omnigent · https://www.databricks.com/blog/introducing-omnigent-meta-harness-combine-control-and-share-your-agents
