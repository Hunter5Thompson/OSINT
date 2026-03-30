# WorldView Demo Playbook

## Prerequisites

```bash
# Start all services
docker compose up -d

# Verify health
curl http://localhost:8080/api/v1/health   # Backend
curl http://localhost:8003/health           # Intelligence
```

Wait for all services to show `healthy` in `docker compose ps`.

## Demo Flow

### 1. Open the UI

Navigate to **http://localhost:5173** in your browser.

You should see:
- CesiumJS 3D Globe with Google Photorealistic Tiles
- Operations Panel (left) with layer toggles
- Clock Bar (top) with multi-timezone display
- Status Bar (bottom) with data counts

### 2. Enable Events Layer

In the Operations Panel, click **EVENTS** to enable intelligence event markers on the globe.

### 3. Run an Intelligence Query

Switch to the **INTEL** tab (right panel, default active).

Enter query:
```
What Chinese military satellites were launched recently?
```

Click **RUN ANALYSIS**. Watch for:
- **Agent status** streaming: shows current processing step
- **Mode badge**: "ReAct" (blue) confirms the new agent architecture
- **Tool chain**: e.g. `qdrant_search → query_knowledge_graph → synthesis`
- **Threat assessment**: color-coded level
- **Analysis text**: structured intelligence report

### 4. Explore the Knowledge Graph

Click the **GRAPH** tab in the right panel.

Search for an entity (e.g., "Yaogan" or "PLA").

You should see:
- Force-directed graph with colored nodes by entity type
- Click nodes to expand their connections
- Right-click to collapse

### 5. Legacy Mode Demo

Back in the **INTEL** tab:
1. Check the **LEGACY MODE** checkbox
2. Run the same query
3. Observe: Mode badge shows "Legacy" (amber), tool chain shows `osint_agent → analyst_agent → synthesis_agent`

### 6. Event Markers on Globe

With the EVENTS layer enabled:
- Diamond-shaped markers appear at event locations
- Colors indicate category (red=military, cyan=space, purple=cyber, etc.)
- Click a marker to see event details (title, type, severity, location)

## Troubleshooting

| Issue | Fix |
|-------|-----|
| No events on globe | Check Neo4j has data: `MATCH (ev:Event)-[:OCCURRED_AT]->(l:Location) RETURN count(ev)` |
| Intel query hangs | Check vLLM is running: `curl http://localhost:8000/health` |
| Graph tab empty | Check Neo4j is running: `curl http://localhost:7474` |
| "ReAct failed" → falls back to Legacy | Expected behavior — check vLLM logs for tool calling errors |
