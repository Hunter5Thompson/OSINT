import json

from munin_distill.harvest import collect_contexts, fire_query


def test_collects_capture_jsons(tmp_path):
    (tmp_path / "a.json").write_text(
        json.dumps({"query": "q1", "system": "S", "human": "H"}, ensure_ascii=False)
    )
    rows = collect_contexts(str(tmp_path))
    assert rows == [{"id": "a", "query": "q1", "system": "S", "human": "H"}]


class _Resp:
    def __init__(self, status: int = 200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _Client:
    def __init__(self, status: int = 200):
        self.status = status
        self.calls: list = []

    def post(self, url, json, timeout):  # noqa: A002 - mirrors httpx.Client.post signature
        self.calls.append((url, json, timeout))
        return _Resp(self.status)


def test_fire_query_posts_payload():
    c = _Client()
    fire_query(c, "http://localhost:8003/query", "q")
    assert c.calls[0][0] == "http://localhost:8003/query"
    assert c.calls[0][1] == {"query": "q"}


def test_fire_query_raises_on_http_error():
    import pytest

    c = _Client(status=500)
    with pytest.raises(RuntimeError):
        fire_query(c, "http://localhost:8003/query", "q")
