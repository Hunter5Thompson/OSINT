# TASK-007 Nachtrag: Hybrid Vision Pipeline (Satellite/Military Imagery)
# Einfügen nach TASK-005, vor TASK-006 (Demo)
# TASK-006 (Demo) wird zu TASK-008

---

## TASK-007: Hybrid Vision — YOLOv8 Detector + Qwen3.5 Reasoner

### Aufwand: 5-7 Tage | Blocked by: TASK-005 | Blocks: TASK-008 (Demo)

### Kontext
Qwen3.5 Vision (aus TASK-005) kann Bilder beschreiben und Fragen beantworten,
aber es kann KEINE militärischen Fahrzeuge in Satellitenbildern zuverlässig
erkennen — die Trainingsdaten fehlen. YOLOv8 erreicht nach Fine-Tuning auf
Aerial/Satellite-Datensätzen mAP@0.5 von 0.79+ für Militärfahrzeuge und
F1=0.958 auf SAR-Daten. Die Hybrid-Pipeline kombiniert beides:
YOLOv8 detektiert → Qwen3.5 reasoned.

### Deliverables
1. `vision/detector.py` — YOLOv8 Military Object Detection
2. `vision/hybrid_pipeline.py` — Orchestrator: Detect → Crop → Reason
3. `vision/training/` — Fine-Tuning Script + Datensatz-Download
4. `services/backend/app/routers/vision.py` — Vision API Endpoints
5. `services/intelligence/agents/tools/vision.py` — ERWEITERT um Detector
6. Integration: Detektierte Objekte → Neo4j als :MilitaryAsset Entities
7. Tests

### Spezifikation

#### Hybrid-Pipeline Architektur
```
Satellitenbild / Aerial Image
    ↓
┌─────────────────────────────────────────────┐
│  YOLOv8m (fine-tuned)  — ~2 GB VRAM        │
│  Erkennt: Bounding Boxes + Klasse + Conf    │
│  z.B. "tank (0.87)", "SAM_system (0.72)"   │
└────────────────┬────────────────────────────┘
                 ↓
    Für jede Detection mit confidence > 0.5:
                 ↓
┌─────────────────────────────────────────────┐
│  Crop + Context Window (2x BBox)            │
│  → Qwen3.5 Vision (already loaded, 0 GB)   │
│  Prompt: "This cropped satellite image      │
│  shows a detected [class]. Identify the     │
│  specific type, assess operational status,  │
│  and note any tactical context."            │
└────────────────┬────────────────────────────┘
                 ↓
┌─────────────────────────────────────────────┐
│  Structured Output:                         │
│  {                                          │
│    "vehicle_type": "T-72B3",               │
│    "status": "operational",                │
│    "context": "Part of convoy, 3 vehicles",│
│    "confidence": 0.87,                     │
│    "bbox": [x1, y1, x2, y2]               │
│  }                                          │
└────────────────┬────────────────────────────┘
                 ↓
    Neo4j: CREATE (:MilitaryAsset) → DETECTED_IN → (:Event)
    Qdrant: Embed detection context für RAG
    Frontend: Overlay BBoxes auf CesiumJS Globe
```

#### VRAM-Budget
```
Modus A + Vision:
  Qwen3.5-27B AWQ:          ~16 GB (bereits geladen)
  Qwen3-Embedding-0.6B:      ~1.2 GB
  YOLOv8m:                    ~2 GB
  ──────────────────────────────────
  Total:                     ~19.2 GB / 32 GB ✅
  Headroom:                  ~12.8 GB
```
YOLOv8m ist klein genug um persistent neben dem LLM zu laufen.

#### vision/detector.py
```python
from ultralytics import YOLO
from PIL import Image
from pydantic import BaseModel

class Detection(BaseModel):
    class_name: str
    confidence: float
    bbox: list[float]  # [x1, y1, x2, y2] normalized
    crop_path: str | None = None

class MilitaryDetector:
    def __init__(self, model_path: str = "models/yolov8m-military.pt"):
        self.model = YOLO(model_path)

    async def detect(self, image_path: str, conf_threshold: float = 0.5) -> list[Detection]:
        results = self.model(image_path, conf=conf_threshold)
        detections = []
        for r in results:
            for box in r.boxes:
                detections.append(Detection(
                    class_name=r.names[int(box.cls)],
                    confidence=float(box.conf),
                    bbox=box.xyxyn.tolist()[0],  # normalized coords
                ))
        return detections

    async def detect_and_crop(self, image_path: str, output_dir: str = "/tmp/crops") -> list[Detection]:
        """Detect + save cropped regions for Qwen3.5 reasoning."""
        img = Image.open(image_path)
        detections = await self.detect(image_path)
        for i, det in enumerate(detections):
            x1, y1, x2, y2 = det.bbox
            w, h = img.size
            # Context window: 2x bbox für umgebenden Kontext
            pad_x, pad_y = (x2-x1) * 0.5, (y2-y1) * 0.5
            crop = img.crop((
                max(0, int((x1-pad_x)*w)), max(0, int((y1-pad_y)*h)),
                min(w, int((x2+pad_x)*w)), min(h, int((y2+pad_y)*h))
            ))
            crop_path = f"{output_dir}/det_{i}_{det.class_name}.jpg"
            crop.save(crop_path)
            det.crop_path = crop_path
        return detections
```

#### vision/hybrid_pipeline.py
```python
class HybridVisionPipeline:
    def __init__(self, detector: MilitaryDetector, llm_client, graph_client):
        self.detector = detector
        self.llm = llm_client
        self.graph = graph_client

    async def analyze_satellite_image(
        self, image_path: str, source_url: str = "", location_name: str = ""
    ) -> list[dict]:
        """
        Full pipeline: Detect → Crop → Reason → Graph Write
        Returns list of analyzed detections with LLM reasoning.
        """
        # Step 1: YOLOv8 Detection + Cropping
        detections = await self.detector.detect_and_crop(image_path)

        results = []
        for det in detections:
            # Step 2: Qwen3.5 Vision Reasoning per Crop
            reasoning = await self.llm.chat.completions.create(
                model="qwen3.5-27b",
                response_format={"type": "json_object"},
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"file://{det.crop_path}"}},
                        {"type": "text", "text": f"""This cropped satellite/aerial image shows a detected {det.class_name} (confidence: {det.confidence:.2f}).
Analyze and respond in JSON:
{{"vehicle_type": "specific type e.g. T-72B3, S-400, Type 055",
  "category": "armor|artillery|air_defense|naval|aircraft|logistics|infrastructure",
  "operational_status": "operational|damaged|destroyed|unknown",
  "tactical_context": "brief description of surroundings and tactical significance",
  "count": 1}}"""}
                    ]
                }],
                temperature=0.1,
            )
            analysis = json.loads(reasoning.choices[0].message.content)
            analysis["detection"] = det.model_dump()

            # Step 3: Neo4j Write — deterministic templates
            await self.graph.run_query(
                """
                MERGE (a:MilitaryAsset {vehicle_type: $vehicle_type})
                SET a.category = $category, a.last_seen = datetime()
                WITH a
                CREATE (d:Detection {
                    timestamp: datetime(),
                    confidence: $confidence,
                    status: $status,
                    context: $context,
                    image_source: $source,
                    location: $location
                })
                CREATE (d)-[:IDENTIFIED]->(a)
                """,
                {
                    "vehicle_type": analysis["vehicle_type"],
                    "category": analysis["category"],
                    "confidence": det.confidence,
                    "status": analysis["operational_status"],
                    "context": analysis["tactical_context"],
                    "source": source_url,
                    "location": location_name,
                }
            )
            results.append(analysis)

        return results
```

#### Fine-Tuning Setup
```python
# vision/training/finetune_yolo.py
from ultralytics import YOLO

# Datensätze (frei verfügbar):
# - xView: 60 Klassen, ~1M Objekte, Satellitenperspektive
#   Download: https://xviewdataset.org/
# - DOTA v2: Aerial Object Detection, 18 Klassen inkl. Fahrzeuge
#   Download: https://captain-whu.github.io/DOTA/
# - FAIR1M: Militärfahrzeuge, Flugzeuge, Schiffe aus Satelliten
#   Download: https://www.gaofen-challenge.com/

# Custom YAML für Military-Klassen (Subset aus xView/DOTA):
# classes: [tank, armored_vehicle, self_propelled_artillery,
#           truck, SAM_system, radar, helicopter, fighter_jet,
#           transport_aircraft, naval_vessel, submarine]

model = YOLO("yolov8m.pt")  # Pretrained auf COCO als Basis
results = model.train(
    data="military_dataset.yaml",
    epochs=100,
    imgsz=1024,         # Satelliten-Auflösung braucht große Input-Size
    batch=8,            # RTX 5090 mit 32GB
    device=0,
    name="yolov8m-military",
    patience=20,
    augment=True,        # Rotation, Flip, Mosaic für Aerial
)
# Output: runs/detect/yolov8m-military/weights/best.pt
# → Kopieren nach models/yolov8m-military.pt
```

#### API Endpoints
```python
# services/backend/app/routers/vision.py

@router.post("/analyze")
async def analyze_image(file: UploadFile, location: str = "", source: str = ""):
    """General image analysis via Qwen3.5 Vision (aus TASK-005)."""

@router.post("/detect/military")
async def detect_military(file: UploadFile, location: str = "", source: str = ""):
    """Hybrid pipeline: YOLOv8 detect → Qwen3.5 reason → Neo4j write."""
    detections = await hybrid_pipeline.analyze_satellite_image(
        image_path=saved_path, source_url=source, location_name=location
    )
    return {"detections": detections, "count": len(detections)}

@router.get("/assets")
async def list_military_assets(category: str = None, since_hours: int = 24):
    """List detected military assets from Neo4j."""
```

#### Agent Tool Erweiterung
```python
# services/intelligence/agents/tools/vision.py — ERWEITERT

@tool
async def detect_military_objects(image_path: str, location: str = "") -> str:
    """Detect and classify military vehicles/equipment in satellite or aerial imagery.
    Use this when analyzing satellite images for military assets like tanks, SAM systems,
    naval vessels, or aircraft."""
    results = await hybrid_pipeline.analyze_satellite_image(image_path, location_name=location)
    if not results:
        return "No military objects detected in this image."
    summary = []
    for r in results:
        summary.append(f"- {r['vehicle_type']} ({r['category']}): {r['operational_status']}, {r['tactical_context']}")
    return f"Detected {len(results)} military objects:\n" + "\n".join(summary)
```

#### Neo4j Schema-Erweiterung
```cypher
// Neue Node Types für Vision
(:MilitaryAsset {vehicle_type, category, last_seen})
(:Detection {timestamp, confidence, status, context, image_source, location})

// Neue Relationships
(:Detection)-[:IDENTIFIED]->(:MilitaryAsset)
(:Detection)-[:DETECTED_AT]->(:Location)
(:Event)-[:VISUAL_EVIDENCE]->(:Detection)

// Neue Constraints
CREATE CONSTRAINT military_asset IF NOT EXISTS
  FOR (a:MilitaryAsset) REQUIRE a.vehicle_type IS UNIQUE;
```

### Tests
```
test_yolo_loads_model
test_detect_returns_bboxes (auf Testbild mit bekannten Objekten)
test_detect_and_crop_saves_files
test_hybrid_pipeline_full (mocked LLM + mocked Neo4j)
test_hybrid_writes_military_asset_to_neo4j
test_api_endpoint_detect_military
test_agent_tool_detect_military_objects
test_vram_budget_yolo_plus_qwen (assert total < 20 GB)
```

### Dependencies
```
ultralytics>=8.2   # YOLOv8
Pillow>=10.0       # Image Processing (wahrscheinlich schon da)
```

### Datensatz-Beschaffung (einmalig, vor Fine-Tuning)
```bash
# xView Dataset (erfordert Registrierung auf xviewdataset.org)
# Nach Download: Konvertierung zu YOLO-Format
python vision/training/convert_xview_to_yolo.py --input xview/ --output datasets/military/

# Alternativ DOTA v2 (kleiner, schneller zum Starten)
# Download von https://captain-whu.github.io/DOTA/
```

### ACHTUNG: Lizenz
ultralytics (YOLOv8) ist AGPL-3.0.
- Für internes Tool / PoC: kein Problem
- Für kommerzielles SaaS: Enterprise License kaufen ODER RT-DETR (Apache 2.0) als Alternative
- Decision: Für MVP AGPL akzeptabel, bei Kommerzialisierung evaluieren

---

# AKTUALISIERTE TASK-REIHENFOLGE:

```
TASK-000: vLLM + Embedding Upgrade           0.5 Tage
    ↓
TASK-001: Neo4j + Two-Loop Graph             3-4 Tage  ┐
TASK-002: Event Codebook + Extractor         2-3 Tage  ┘ parallel
    ↓
TASK-003: Ingestion Pipeline → Graph         3-4 Tage
    ↓
TASK-004: Hybrid Search + Docling            3-4 Tage
    ↓
TASK-005: Agent Tools + Graph Explorer       4-5 Tage
    ↓
TASK-007: Hybrid Vision (YOLOv8 + Qwen3.5)  5-7 Tage   ← NEU
    ↓
TASK-008: Demo + Polish                      2-3 Tage   ← war TASK-006
                                             ──────────
                                             ~24-31 Tage
                                             = 5-7 Wochen bei Abenden/WE
```

# AKTUALISIERTE DEPENDENCIES (gesamt):
```
vllm
sentence-transformers>=3.0
neo4j>=5.23
openai>=1.40
docling[vlm,easyocr]>=2.80
pyyaml>=6.0
ultralytics>=8.2              ← NEU (AGPL-3.0, für MVP ok)
Pillow>=10.0                  ← NEU (vermutlich schon vorhanden)
react-force-graph-2d ^1.25
```
8 Python + 1 Frontend Dependencies.
