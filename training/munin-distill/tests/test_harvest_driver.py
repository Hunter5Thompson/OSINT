import hashlib
import json
from pathlib import Path

from munin_distill.harvest import load_queries, run_harvest


def test_load_queries_handles_missing_trailing_newline(tmp_path):
    p = tmp_path / "q.jsonl"
    # NO trailing newline — the exact condition that dropped the last query in the bash driver
    p.write_text("\n".join(json.dumps({"id": str(i), "query": f"q{i}"}) for i in range(3)))
    rows = load_queries(str(p))
    assert [r["query"] for r in rows] == ["q0", "q1", "q2"]  # all 3 — last NOT dropped


def _key(q: str) -> str:
    # mirrors services/intelligence/distill_capture.capture_synthesis_input
    return hashlib.sha1(q.encode("utf-8")).hexdigest()[:16]


class _FakeResp:
    def raise_for_status(self):
        pass


class _FakeClient:
    """Mimics httpx.Client.post AND the server-side capture hook (writes a capture file on success)."""

    def __init__(self, capture_dir: str, fail_on=()):
        self.capture_dir = Path(capture_dir)
        self.fail_on = set(fail_on)

    def post(self, url, json, timeout):  # noqa: A002 - mirrors httpx signature
        q = json["query"]
        if q in self.fail_on:
            raise RuntimeError("boom")
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        (self.capture_dir / f"{_key(q)}.json").write_text(
            __import__("json").dumps(
                {"query": q, "system": "S", "human": "H Recherche-Ergebnisse:"}
            )
        )
        return _FakeResp()


def test_run_harvest_tolerant_logs_and_consistent(tmp_path):
    cap = tmp_path / "cap"
    qs = [{"query": f"q{i}"} for i in range(5)]
    client = _FakeClient(str(cap), fail_on={"q2"})
    events = []
    s = run_harvest(qs, "http://x/query", str(cap), client, on_event=lambda *a: events.append(a))
    assert s["fired"] == 5
    assert s["ok"] == 4
    assert s["failed"] == 1
    assert s["failures"][0]["query"] == "q2"
    assert s["captured"] == 4
    assert s["capture_complete"] is True       # every OK query produced a capture
    assert s["missing_captures"] == []
    assert len(events) == 5                     # all fires logged (ok + fail)


def test_run_harvest_flags_missing_capture(tmp_path):
    cap = tmp_path / "cap"
    qs = [{"query": "q0"}]

    class _SilentClient:
        # "succeeds" but writes NO capture file (simulates a lost capture)
        def post(self, url, json, timeout):
            return _FakeResp()

    s = run_harvest(qs, "http://x/query", str(cap), _SilentClient())
    assert s["ok"] == 1
    assert s["captured"] == 0
    assert s["capture_complete"] is False
    assert s["missing_captures"] == ["q0"]
