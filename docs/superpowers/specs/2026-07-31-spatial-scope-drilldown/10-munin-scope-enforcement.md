# Teil-Spec 10 — Munin Scope Enforcement

> **Parent:** [Spatial-Scope-Index](../2026-07-31-spatial-scope-drilldown-design.md)
>
> **Normativer Besitz:** Intelligence-Request, gepinnter Run-Snapshot,
> `ToolRuntime`-Injektion, statische Graph-Templates, Tool-Capability-Matrix und
> maschinelles Spatial-Accounting.
>
> **Voraussetzungen:** [08 — Neo4j](08-neo4j-normalization.md) und
> [09 — Qdrant](09-qdrant-retrieval.md); Identität stammt ausschließlich aus
> [02](02-scope-identity-and-boundary-policy.md).

---

## 17. Munin und LangGraph: Scope ist nicht modellkontrolliert

### 17.1 Externer Request

Frontend/Backend-Vertrag:

```ts
interface IntelQuery {
  readonly query: string;
  readonly spatialScope?: SpatialQueryRef;
  readonly spatialRelation?: "about" | "occurrence" | "either";
  readonly imageUrl?: string;
  readonly useLegacy?: boolean;
}
```

Backend löst `spatialScope` auf und sendet intern:

```json
{
  "query": "...",
  "spatial_scope": {
    "schema_version": 1,
    "scope_key": "country:UKR",
    "kind": "country",
    "catalog_revision": "spatial-v1-a1b2c3d4e5f6",
    "derivation_revision": "spatial-derive-v1-112233445566",
    "boundary_policy": "odin-reference-v1",
    "compatible_derivation_revisions": [
      "spatial-derive-v1-112233445566",
      "spatial-derive-v1-aabbccddeeff"
    ]
  },
  "spatial_relation": "either"
}
```

`region` bleibt während einer Deprecation-Phase für alte Caller erhalten. `region + spatial_scope` ergibt `422`; der WorldView-Pfad verwendet nur noch den strukturierten Scope. `region` ist keine Sicherheits- oder Filtergrenze.

`spatial_relation` wird intern nie `None`: Fehlt das optionale externe
`spatialRelation`, initialisiert das Backend sie deterministisch mit `either` — auch
für einen globalen Run. Das Modell entscheidet diesen Default nicht.

Solange der Legacy-Intelligence-Pfad keine identischen deterministischen Filter besitzt,
ergibt `spatial_scope + use_legacy=true` ebenfalls
`422 SPATIAL_SCOPE_UNSUPPORTED_LEGACY`. Der Service darf einen scoped ReAct-Run bei Fehler
nicht automatisch in den ungescopten Legacy-Pfad umleiten.

Der bestehende Country-Briefing-Endpunkt vertraut dabei keinem vom Browser
mitgelieferten Country-Scope: Er löst das bereits serverseitig validierte Almanac-
Country-ID auf, konstruiert dessen kanonischen `country:*`-Key, resolved den Token im
Spatial Catalog und reicht ihn an `stream_intel_query` weiter. Ein generischer Munin-
Run aus dem WorldView verwendet dagegen den committed `SpatialQueryRef` des Moduls.
Beide Wege landen im gleichen internen Token. Das persistierte Dossier behält seinen
vorhandenen kanonischen `scope_key`; Legacy-Aliases werden beim Lookup aufgelöst, aber
nicht destruktiv umgeschrieben.

Für Dossier-Lookup liefert der Catalog eine kleine allowlisted Menge
`[canonical_key, ...legacy_aliases]`. Eine neue statische, parametergebundene
`REPORT_BY_SCOPE_KEYS`-Query sucht `r.scope_key IN $scope_keys`; neue Reports werden
nur mit dem kanonischen Key angelegt. Existieren versehentlich kanonischer und Alias-
Report zugleich, wird nicht automatisch gemerged: der canonical Record gewinnt für
Read, ein Duplicate-Conflict wird geloggt und separat kuratiert.

### 17.2 Gepinnter Run-Snapshot

`AgentState` erhält:

```py
class AgentState(TypedDict):
    # existing fields ...
    spatial_scope: SpatialScopeTokenV1 | None
    spatial_relation: RetrievalSpatialRelation
```

Der Scope wird einmal beim Start des Runs gesetzt. Ein späterer UI-Scope-Wechsel
verändert den laufenden Run nicht. Ergebnis und gespeicherter Report tragen Scope-Key,
Katalog- und Derivationsrevision. Die UI darf ein verspätetes Ergebnis unter neuem
Scope nur mit seinem ursprünglichen Scope-Label anzeigen, niemals still umetikettieren.

`Report.spatial_application` ist der Snapshot des zuletzt erfolgreich am Report
persistierten Intelligence-Runs, nicht eine dauerhafte Eigenschaft des Dossiers. Jeder
Report-Run schreibt das Feld; ein ungescopter Run schreibt explizit `null` und löscht
damit einen älteren scoped Snapshot. Schlägt dieses Update fehl, werden weder die neue
Munin-Message noch ein Result-Event unter dem alten Snapshot veröffentlicht.

`IntelAnalysis` erhält optional:

```ts
interface SpatialRunConsumerApplication {
  readonly status: "applied" | "not-called" | "unsupported" | "failed";
  readonly mode: "global" | "semantic-key";
  readonly completeness: "complete" | "partial" | "unknown";
  readonly detail_code?: string;
}

interface SpatialRunApplicationV1 {
  readonly schema_version: 1;
  readonly scope: {
    readonly schema_version: 1;
    readonly scope_key: string;
    readonly catalog_revision: string;
    readonly derivation_revision: string;
    readonly boundary_policy: string;
  };
  readonly relation: "about" | "occurrence" | "either";
  readonly qdrant: SpatialRunConsumerApplication;
  readonly neo4j: SpatialRunConsumerApplication;
  readonly blocked_tools: readonly string[];
  readonly coverage_revision: string | null;
}
```

Backend- und Frontend-`IntelAnalysis` spiegeln dieses Feld; `intel_stream.py` darf es
beim heutigen Response-Mapping nicht fallenlassen. `not-called` ist kein „complete“:
Completeness bleibt dann `unknown`. Ein Toolfehler wird nicht durch eine erfolgreiche
andere Lane als vollständige räumliche Anwendung dargestellt.

Qdrant-/Graph-Tools schreiben dafür eine kompakte maschinelle erste Zeile
`[SPATIAL_APPLICATION] {json}` in ihre Tool-Response, analog zum bestehenden
`[EVIDENCE]`-Codec. `spatial.py` formatiert und parst die geschlossene Struktur; freier
Modeltext wird nie als Status geparst. `react_synthesis_node` aggregiert pro Consumer:

- kein Call → `not-called/unknown`;
- mindestens ein erfolgreicher Apply → `applied`, Completeness ist der schlechteste
  erfolgreiche Coverage-Status; fehlgeschlagene frühere Versuche bleiben als
  `detail_code=some-attempts-failed` sichtbar;
- nur unsupported Calls → `unsupported`;
- nur fehlgeschlagene Calls → `failed`.

Die Codec-Zeile zählt nicht als Evidence-Quelle und wird vor dem eigentlichen
Synthesis-Research-Text entfernt oder in eine kurze vertrauenswürdige Metanotiz
umgewandelt. `blocked_tools` stammt aus der deterministischen Tool-Capability-Matrix,
nicht aus Modellbehauptungen.

Der Parser akzeptiert den Marker nur als erste Zeile des konkreten ToolMessages,
validiert JSON-Schema sowie `consumer` gegen den tatsächlichen Toolnamen und ignoriert
gleichlautenden Text in Dokument-Content. Damit kann ein Feed/Artikel den Status nicht
spoofen.

### 17.3 ToolRuntime-Injektion

Die lokal installierte API wird so verwendet:

```py
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from graph.state import AgentState


@tool
async def qdrant_search(
    query: str,
    runtime: ToolRuntime[dict[str, object], AgentState],
) -> str:
    """Search vetted ODIN evidence; spatial scope is injected by runtime."""
    scope = runtime.state["spatial_scope"]
    relation = runtime.state["spatial_relation"]
    spatial_filter = compile_qdrant_scope_filter(scope, relation) if scope else None
    return await run_scoped_evidence_search(query, spatial_filter)
```

`runtime` wird von LangGraph injiziert und nicht Teil des modellgesehenen Tool-Schemas. Das heutige modellkontrollierte Argument `region` entfällt aus `qdrant_search`.

### 17.4 Neo4j-Tool

Freies, read-only LLM-Cypher kann nicht zuverlässig nachträglich um einen Scope ergänzt werden. Daher gilt:

- globaler Run: heutiger read-only Fallback bleibt möglich;
- nicht-globaler Run: nur scope-aware, statische Query-Templates werden exponiert;
- ist für eine Frage kein scope-sicheres Template vorhanden, antwortet das Tool mit `SPATIAL_SCOPE_UNSUPPORTED`;
- es erfolgt keine ungefilterte Fallback-Query;
- alle Template-Werte bleiben parametergebunden;
- Writes bleiben in jedem Modus deterministisch und außerhalb des LLM-Pfads.

Mögliche erste scope-sichere Intents: Events im Zeitfenster, Entities über scoped Events, Location-Facts, notable activity und Country/Admin-Briefing-Evidence.

Konkret erhält `query_knowledge_graph(question, runtime: ToolRuntime[...])` denselben
injected State wie Qdrant. `_match_intent()` darf weiterhin den fachlichen Template-
Intent erkennen, aber `execute_graph_query()` wählt bei nicht-globalem Scope aus einer
separaten `SCOPED_TEMPLATES[(template_id, scope_kind)]`-Registry mit vollständigen,
statischen Query-Strings. Es hängt kein dynamisches `WHERE` an vorhandenes Cypher an.

Erste Freigabematrix:

| Template | scoped V1 | Scope-Pfad |
|---|---:|---|
| `event_timeline` | ja | Event → `OCCURRED_AT` → Location-Scope-Key |
| `events_by_entity` | ja | Entity ← Event → Location-Scope-Key |
| `source_backed` | ja | Source ← Event → Location-Scope-Key |
| `co_occurring` | ja | beide Entities über dasselbe scoped Event |
| `entity_lookup` | nein | globale Stammdaten wären kein scoped Ergebnis |
| `one_hop` / `two_hop_network` | nein | freie Pfade können Scope verlassen |
| `top_connected` | nein | heutige Query ist explizit global |
| Free-Cypher-Fallback | nein | nicht sicher generisch constrainbar |

Jede scoped Variante bindet `$scope_key` und `$compatible_revisions`; Country,
Admin-1 und Admin-2 besitzen jeweils ein vollständiges allowlisted Template, damit
Neo4j den passenden Composite-Index planen kann. Ein nicht freigegebenes Mapping gibt
strukturiert `SPATIAL_SCOPE_UNSUPPORTED` zurück und führt keine Query aus.

### 17.5 Tool-Capability-Matrix für scoped Runs

Scope-Enforcement endet nicht bei Neo4j/Qdrant. Der aktuelle ReAct-Agent bindet sechs
Tools; jedes wird klassifiziert:

| Tool | nicht-globaler Run | Regel |
|---|---|---|
| `qdrant_search` | erlaubt | Runtime-gebundener About/Occurrence-Filter |
| `query_knowledge_graph` | erlaubt, Teilmenge | scoped Template-Matrix; sonst unsupported |
| `classify_event` | erlaubt | reine Transformation explizit übergebenen Texts, keine Retrieval-Quelle |
| `analyze_image` | nur attached image | URL kommt aus `AgentState.image_url`, nicht vom Modell; kein räumlicher Retrieval-Consumer |
| `gdelt_query` | gesperrt | DOC-Keyword-Query garantiert keinen semantischen Raum |
| `rss_fetch` | gesperrt | ein Feed besitzt keinen Scope-Constraint |

`tools_for_state(state)` bindet dem LLM bei einem nicht-globalen Run nur die erlaubten
Tools. Der bestehende kompilierte `ToolNode` darf aus Lifecycle-Gründen weiterhin die
Gesamtmenge kennen; Defense in Depth: `gdelt_query` und `rss_fetch` erhalten ebenfalls
einen versteckten `ToolRuntime`-Parameter und geben vor jeglichem HTTP-Aufruf
`SPATIAL_SCOPE_UNSUPPORTED` zurück, falls ein Modell trotzdem einen nicht gebundenen
Toolnamen erzeugt. Es gibt dann keinen Network-Call und keinen Evidence-Block.

`analyze_image` wird zu `analyze_image(question, runtime)`; es liest exakt die am
Request validierte `state["image_url"]`. Ohne attached image wird es nicht gebunden und
führt auch bei direktem Call nichts aus. Damit kann das Modell weder im scoped noch im
globalen Run eine beliebige neue Bild-URL als Neben-Retrieval wählen.
Vision belegt bewusst keinen Slot in `SpatialRunApplicationV1`: Der Vertrag beschreibt
nur die räumliche Anwendung der beiden Retrieval-Consumer Qdrant und Neo4j.

Der globale Run behält GDELT/RSS. Da `gdelt_query.py` in Slice 7 ohnehin geändert wird,
wandert seine vorhandene externe URL in `config.py`; die AGENTS-Regel „keine
hardcodierten URLs“ gilt auch hier. Ein späterer scoped GDELT-Adapter benötigt einen
eigenen verifizierten Vertrag und wird nicht durch das Anhängen eines Country-Namens
an den modellgenerierten Suchtext simuliert.

### 17.6 Prompting

Der Prompt darf den aktiven Scope für Transparenz nennen. Er ist jedoch nur Erläuterung. Enforcement entsteht ausschließlich durch den gebundenen Runtime-State und die deterministischen Filter-Compiler. Ein Prompt-Injection-Text kann den Scope damit weder ändern noch entfernen.

---
