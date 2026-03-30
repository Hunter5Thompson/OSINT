# TASK-102: Event Codebook + IntelligenceExtractor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an Event Codebook (YAML taxonomy, 50+ event types) and a combined IntelligenceExtractor that does event classification + entity extraction in one LLM call via vLLM structured output.

**Architecture:** `codebook/loader.py` loads the YAML taxonomy and provides utility functions. `codebook/extractor.py` holds `IntelligenceExtractor` which builds a system prompt from the codebook, makes one vLLM call, and returns classified events + extracted entities + locations. Post-validation remaps unknown event types to `other.unclassified` and filters low-confidence events. Entity types use lowercase to match `graph/models.py`.

**Tech Stack:** `pyyaml>=6.0`, `openai>=1.40`, httpx, Pydantic v2, pytest

**Working directory:** `services/intelligence/`

**Run tests with:** `cd services/intelligence && uv run python -m pytest tests/ -v --tb=short`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `pyproject.toml` | MODIFY | Add pyyaml, openai dependencies |
| `codebook/__init__.py` | CREATE | Package init + exports |
| `codebook/event_codebook.yaml` | CREATE | 50+ event types in 10 categories |
| `codebook/loader.py` | CREATE | load_codebook, get_all_event_types, validate_codebook |
| `codebook/extractor.py` | CREATE | IntelligenceExtractor + IntelligenceExtractionResult |
| `tests/test_codebook.py` | CREATE | 6+ tests with mocked vLLM responses |

---

## Task 1: Add dependencies (pyyaml, openai)

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add to dependencies**

Add `"pyyaml>=6.0"` and `"openai>=1.40"` to the `dependencies` list. Add `"codebook/**/*.py"` and `"codebook/**/*.yaml"` to `[tool.hatch.build.targets.wheel] include`.

- [ ] **Step 2: Install**

Run: `uv sync`

- [ ] **Step 3: Verify**

Run: `uv run python -c "import yaml; import openai; print('OK')"`

---

## Task 2: Event Codebook YAML

**Files:**
- Create: `codebook/__init__.py` (empty)
- Create: `codebook/event_codebook.yaml`

- [ ] **Step 1: Create empty package init**

```python
# codebook/__init__.py
```

- [ ] **Step 2: Create event_codebook.yaml**

Structure:
```yaml
version: "1.0"
categories:
  military:
    label: "Military"
    types:
      - type: "military.airstrike"
        label: "Airstrike"
        description: "Fixed-wing or rotary-wing aircraft strike on a target"
      # ... 6-7 types per category
```

**Required categories (10):** military, political, economic, space, cyber, environmental, social, humanitarian, infrastructure, other.

**Minimum 50 total types.** Use dotted notation (`category.subcategory`) so Neo4j queries can use `STARTS WITH 'military.'`.

The `other` category must contain at least `other.unclassified` as the fallback type.

---

## Task 3: Codebook loader (TDD)

**Files:**
- Create: `tests/test_codebook.py` (loader tests only first)
- Create: `codebook/loader.py`

- [ ] **Step 1: Write failing tests for loader**

```python
# tests/test_codebook.py
"""Tests for event codebook loader and IntelligenceExtractor."""

import pytest
from codebook.loader import load_codebook, get_all_event_types, validate_codebook


class TestCodebookLoader:
    def test_codebook_loads_successfully(self):
        codebook = load_codebook()
        assert "version" in codebook
        assert "categories" in codebook

    def test_all_ten_categories_present(self):
        codebook = load_codebook()
        expected = {"military", "political", "economic", "space", "cyber",
                    "environmental", "social", "humanitarian", "infrastructure", "other"}
        assert set(codebook["categories"].keys()) == expected

    def test_minimum_fifty_event_types(self):
        codebook = load_codebook()
        all_types = get_all_event_types(codebook)
        assert len(all_types) >= 50, f"Only {len(all_types)} types, need >= 50"

    def test_all_types_use_dotted_notation(self):
        codebook = load_codebook()
        for t in get_all_event_types(codebook):
            assert "." in t, f"Type '{t}' missing dotted notation"

    def test_other_unclassified_exists(self):
        codebook = load_codebook()
        all_types = get_all_event_types(codebook)
        assert "other.unclassified" in all_types

    def test_validate_codebook_passes(self):
        codebook = load_codebook()
        validate_codebook(codebook)  # should not raise

    def test_validate_codebook_rejects_empty(self):
        with pytest.raises(ValueError):
            validate_codebook({})
```

- [ ] **Step 2: Run tests, verify they fail (ModuleNotFoundError)**

- [ ] **Step 3: Implement loader.py**

```python
# codebook/loader.py
"""Load and validate the event codebook YAML."""

from __future__ import annotations

from pathlib import Path
import yaml


_DEFAULT_PATH = Path(__file__).parent / "event_codebook.yaml"


def load_codebook(path: Path | None = None) -> dict:
    """Load the event codebook from YAML."""
    p = path or _DEFAULT_PATH
    with open(p) as f:
        return yaml.safe_load(f)


def get_all_event_types(codebook: dict) -> list[str]:
    """Flatten the codebook hierarchy into a sorted list of dotted type strings."""
    types = []
    for category in codebook.get("categories", {}).values():
        for entry in category.get("types", []):
            types.append(entry["type"])
    return sorted(types)


def validate_codebook(codebook: dict) -> None:
    """Validate codebook structure. Raises ValueError on failure."""
    if "version" not in codebook:
        raise ValueError("Codebook missing 'version' key")
    if "categories" not in codebook:
        raise ValueError("Codebook missing 'categories' key")
    all_types = get_all_event_types(codebook)
    if len(all_types) < 50:
        raise ValueError(f"Codebook has {len(all_types)} types, need >= 50")
    if "other.unclassified" not in all_types:
        raise ValueError("Codebook missing 'other.unclassified' fallback type")
```

- [ ] **Step 4: Run tests, verify all pass**

- [ ] **Step 5: Run full suite, no regressions**

---

## Task 4: IntelligenceExtractor (TDD)

**Files:**
- Modify: `tests/test_codebook.py` (add extractor tests)
- Create: `codebook/extractor.py`

- [ ] **Step 1: Add failing extractor tests to test_codebook.py**

```python
from unittest.mock import AsyncMock, patch, MagicMock
import json
from codebook.extractor import IntelligenceExtractor, IntelligenceExtractionResult


def _mock_vllm_response(content: dict) -> MagicMock:
    """Build a mock httpx Response matching vLLM chat completion format."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(content)}}]
    }
    return mock_resp


class TestIntelligenceExtractor:
    async def test_extract_military_event(self):
        mock_content = {
            "events": [{
                "title": "Drone strike on Odessa",
                "summary": "Russian forces launched drone attack",
                "codebook_type": "military.drone_attack",
                "severity": "high",
                "confidence": 0.9,
                "timestamp": "2026-03-30T10:00:00Z",
            }],
            "entities": [{
                "name": "Russian Armed Forces",
                "type": "organization",
                "confidence": 0.85,
            }],
            "locations": [{"name": "Odessa", "country": "Ukraine"}],
        }

        with patch("codebook.extractor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_vllm_response(mock_content)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            extractor = IntelligenceExtractor()
            result = await extractor.extract("Russian forces launched drone attack on Odessa port")

        assert len(result.events) == 1
        assert result.events[0].codebook_type.startswith("military.")
        assert len(result.entities) >= 1

    async def test_extract_space_event(self):
        mock_content = {
            "events": [{
                "title": "Yaogan-44 satellite launch",
                "summary": "China launched Yaogan-44 from Jiuquan",
                "codebook_type": "space.satellite_launch",
                "severity": "medium",
                "confidence": 0.95,
                "timestamp": "2026-03-28T02:00:00Z",
            }],
            "entities": [
                {"name": "Yaogan-44", "type": "satellite", "confidence": 0.9},
                {"name": "PLA Strategic Support Force", "type": "military_unit", "confidence": 0.8},
            ],
            "locations": [{"name": "Jiuquan", "country": "China"}],
        }

        with patch("codebook.extractor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_vllm_response(mock_content)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            extractor = IntelligenceExtractor()
            result = await extractor.extract("China launched Yaogan-44 from Jiuquan")

        assert result.events[0].codebook_type.startswith("space.")
        assert any(e.name == "Yaogan-44" for e in result.entities)

    async def test_extract_returns_valid_pydantic_model(self):
        mock_content = {
            "events": [{"title": "Test", "summary": "", "codebook_type": "military.airstrike",
                        "severity": "low", "confidence": 0.5, "timestamp": "2026-01-01T00:00:00Z"}],
            "entities": [{"name": "NATO", "type": "organization", "confidence": 0.7}],
            "locations": [],
        }

        with patch("codebook.extractor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_vllm_response(mock_content)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            extractor = IntelligenceExtractor()
            result = await extractor.extract("NATO conducted an airstrike")

        assert isinstance(result, IntelligenceExtractionResult)
        assert all(0 <= e.confidence <= 1 for e in result.entities)
        assert all(0 <= ev.confidence <= 1 for ev in result.events)

    async def test_unknown_event_defaults_to_other(self):
        mock_content = {
            "events": [{"title": "Unknown", "summary": "", "codebook_type": "nonsense.invalid",
                        "severity": "low", "confidence": 0.6, "timestamp": "2026-01-01T00:00:00Z"}],
            "entities": [],
            "locations": [],
        }

        with patch("codebook.extractor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_vllm_response(mock_content)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            extractor = IntelligenceExtractor()
            result = await extractor.extract("Something unknown happened")

        assert result.events[0].codebook_type == "other.unclassified"

    async def test_confidence_below_threshold_filtered(self):
        mock_content = {
            "events": [
                {"title": "Weak", "summary": "", "codebook_type": "military.airstrike",
                 "severity": "low", "confidence": 0.1, "timestamp": "2026-01-01T00:00:00Z"},
                {"title": "Strong", "summary": "", "codebook_type": "military.airstrike",
                 "severity": "high", "confidence": 0.9, "timestamp": "2026-01-01T00:00:00Z"},
            ],
            "entities": [],
            "locations": [],
        }

        with patch("codebook.extractor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_vllm_response(mock_content)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            extractor = IntelligenceExtractor(confidence_threshold=0.3)
            result = await extractor.extract("Military activity reported")

        assert len(result.events) == 1
        assert result.events[0].title == "Strong"
```

- [ ] **Step 2: Run tests, verify they fail (ModuleNotFoundError for codebook.extractor)**

- [ ] **Step 3: Implement codebook/extractor.py**

The `IntelligenceExtractor` class:
- Constructor: loads codebook, caches flat type list, builds system prompt
- `async def extract(text, source_url, max_chars) -> IntelligenceExtractionResult`
- Post-validation: unknown codebook_type → `other.unclassified`, low confidence events filtered
- Uses `httpx.AsyncClient` to POST to vLLM (same pattern as entity_extractor.py)

Pydantic models in extractor.py:
```python
class ExtractedEventRaw(BaseModel):
    title: str
    summary: str = ""
    codebook_type: str
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0, le=1)
    timestamp: str = ""

class ExtractedEntityRaw(BaseModel):
    name: str
    type: Literal["person", "organization", "location", "weapon_system",
                  "satellite", "vessel", "aircraft", "military_unit"]
    confidence: float = Field(ge=0, le=1, default=0.5)

class ExtractedLocationRaw(BaseModel):
    name: str
    country: str

class IntelligenceExtractionResult(BaseModel):
    events: list[ExtractedEventRaw] = Field(default_factory=list)
    entities: list[ExtractedEntityRaw] = Field(default_factory=list)
    locations: list[ExtractedLocationRaw] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests, verify all pass**

- [ ] **Step 5: Run full suite, no regressions**

---

## Task 5: Package wiring + final verification

**Files:**
- Modify: `codebook/__init__.py`
- Modify: `pyproject.toml` (build includes)

- [ ] **Step 1: Update codebook/__init__.py exports**

```python
from codebook.loader import load_codebook, get_all_event_types
from codebook.extractor import IntelligenceExtractor, IntelligenceExtractionResult

__all__ = [
    "load_codebook", "get_all_event_types",
    "IntelligenceExtractor", "IntelligenceExtractionResult",
]
```

- [ ] **Step 2: Verify imports**

Run: `uv run python -c "from codebook import IntelligenceExtractor, load_codebook, get_all_event_types; print(f'{len(get_all_event_types(load_codebook()))} event types loaded')"`
Expected: `5X event types loaded` (>= 50)

- [ ] **Step 3: Run full test suite**

Run: `uv run python -m pytest tests/ -v --tb=short`
Expected: All 69+ existing tests + ~12 new codebook tests pass

- [ ] **Step 4: Commit**

```bash
git add codebook/ tests/test_codebook.py pyproject.toml
git commit -m "feat(codebook): TASK-102 — Event Codebook + IntelligenceExtractor"
```
