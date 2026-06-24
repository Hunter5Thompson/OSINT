import json

from langchain_core.messages import HumanMessage, SystemMessage

from distill_capture import capture_synthesis_input


def test_noop_without_env(tmp_path, monkeypatch):
    monkeypatch.delenv("DISTILL_CAPTURE_DIR", raising=False)
    capture_synthesis_input("q", [SystemMessage(content="s"), HumanMessage(content="h")])
    assert list(tmp_path.iterdir()) == []


def test_writes_exact_pair(tmp_path, monkeypatch):
    monkeypatch.setenv("DISTILL_CAPTURE_DIR", str(tmp_path))
    capture_synthesis_input(
        "query-x", [SystemMessage(content="SYS"), HumanMessage(content="HUMAN")]
    )
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data == {"query": "query-x", "system": "SYS", "human": "HUMAN"}
