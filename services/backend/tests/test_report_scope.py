# services/backend/tests/test_report_scope.py
import pytest
from neo4j.exceptions import ConstraintError

from app.models.report import ReportCreateRequest, ReportUpdateRequest
from app.services import report_store


def _req(**kw) -> ReportCreateRequest:
    return ReportCreateRequest(title="T", location="L", coords="--", **kw)


class _FakeGraph:
    """In-memory Report store with a scope_key uniqueness index."""

    def __init__(self) -> None:
        self.by_id: dict[str, dict] = {}

    async def write(self, cypher, params):
        is_create = "CREATE (r:Report" in cypher
        is_upsert = "MERGE (r:Report" in cypher and "scope_key = $scope_key" in cypher
        if is_create or is_upsert:
            rid, scope = params["report_id"], params.get("scope_key")
            if is_create and rid in self.by_id:  # CREATE → real id uniqueness
                raise ConstraintError("already exists, constraint `report_id_unique`")
            if scope is not None and any(
                r.get("scope_key") == scope and i != rid for i, r in self.by_id.items()
            ):
                raise ConstraintError("already exists, constraint `report_scope_key_unique`")
            self.by_id[rid] = dict(params)
            return [self._row(rid)]
        return []

    async def read(self, cypher, params):
        if "scope_key: $scope_key" in cypher:
            hit = next(
                (r for r in self.by_id.values() if r.get("scope_key") == params["scope_key"]),
                None,
            )
            return [self._row(hit["report_id"])] if hit else []
        if "max(r.paragraph_num)" in cypher:
            nxt = max((r["paragraph_num"] for r in self.by_id.values()), default=0) + 1
            return [{"next_paragraph": nxt}]
        rid = params.get("report_id")
        return [self._row(rid)] if rid in self.by_id else []

    def _row(self, rid):
        p = self.by_id[rid]
        return {
            "id": rid,
            "scope_key": p.get("scope_key"),
            "paragraph_num": p.get("paragraph_num", 0),
            "title": p.get("title", ""),
            "confidence": p.get("confidence", 0.0),
        }


@pytest.fixture
def graph(monkeypatch):
    g = _FakeGraph()
    monkeypatch.setattr(report_store, "write_query", g.write)
    monkeypatch.setattr(report_store, "read_query", g.read)
    return g


@pytest.mark.asyncio
async def test_scope_key_roundtrips_and_survives_update(graph):
    rec = await report_store.create_report(_req(scope_key="country:DEU"))
    assert rec.scope_key == "country:DEU"
    updated = await report_store.update_report(rec.id, ReportUpdateRequest(confidence=0.9))
    assert updated.scope_key == "country:DEU"  # survived the update


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent_per_scope(graph):
    a = await report_store.get_or_create_report_by_scope(
        "country:FRA", title="F", location="F", coords="--"
    )
    b = await report_store.get_or_create_report_by_scope(
        "country:FRA", title="F", location="F", coords="--"
    )
    assert a.id == b.id  # reuse, not a second dossier


@pytest.mark.asyncio
async def test_create_report_reraises_scope_conflict_not_id_retry(graph):
    await report_store.create_report(_req(scope_key="country:ITA"))
    # scope error must NOT be swallowed by the id-retry loop
    with pytest.raises(ConstraintError):
        await report_store.create_report(_req(scope_key="country:ITA"))


@pytest.mark.asyncio
async def test_create_report_retries_id_race_then_succeeds(graph, monkeypatch):
    # Two creates forced onto the SAME paragraph (r-001): the second CREATE raises
    # report_id_unique → get_report finds r-001 → retry with r-002. (Scope path is the
    # test above, where the id does NOT resolve → re-raise.)
    seq = iter([1, 1, 2])

    async def fake_next():
        return next(seq)

    monkeypatch.setattr(report_store, "_next_paragraph", fake_next)
    first = await report_store.create_report(_req(scope_key="country:AAA"))
    assert first.id == "r-001"
    second = await report_store.create_report(_req(scope_key="country:BBB"))
    assert second.id == "r-002"  # r-001 taken → CREATE raises → retried to r-002


@pytest.mark.asyncio
async def test_get_or_create_rereads_winner_on_scope_race(monkeypatch):
    # True race: scope read misses, the CREATE loses to a concurrent racer (scope ConstraintError),
    # the racer's id (r-005) ≠ our id (r-009) so create_report re-raises, and get_or_create re-reads
    # the winner via REPORT_BY_SCOPE.
    winner = {"id": "r-005", "scope_key": "country:RACE", "paragraph_num": 5}
    reads = {"scope": 0}

    async def read(cypher, params):
        if "scope_key: $scope_key" in cypher:
            reads["scope"] += 1
            return [] if reads["scope"] == 1 else [winner]  # miss, then the racer's winner
        if "max(r.paragraph_num)" in cypher:
            return [{"next_paragraph": 9}]  # our create computes r-009 (≠ winner r-005)
        return []  # get_report(r-009) → None → re-raise

    async def write(cypher, params):
        raise ConstraintError("constraint `report_scope_key_unique`")

    monkeypatch.setattr(report_store, "read_query", read)
    monkeypatch.setattr(report_store, "write_query", write)
    got = await report_store.get_or_create_report_by_scope(
        "country:RACE", title="x", location="x", coords="--"
    )
    assert got.id == "r-005"  # re-read the winner after losing the create race


@pytest.mark.asyncio
async def test_bootstrap_creates_both_constraints(monkeypatch):
    calls: list[str] = []

    async def write(cypher, params):
        calls.append(cypher)
        return []

    monkeypatch.setattr(report_store, "write_query", write)
    await report_store.bootstrap_report_schema()
    assert any("report_id_unique" in c for c in calls)
    assert any("report_scope_key_unique" in c for c in calls)


@pytest.mark.asyncio
async def test_update_report_accepts_metrics_patch_without_crashing(graph):
    # Regression: hydration sends DossierMetric objects through update_report → _report_params.
    # Without the merged-record re-validation this raises AttributeError on dict.model_dump().
    from app.models.report import DossierMetric

    rec = await report_store.create_report(_req(scope_key="country:MET"))
    updated = await report_store.update_report(
        rec.id,
        ReportUpdateRequest(
            metrics=[DossierMetric(label="Threat", value="HIGH", sub="assessment", tone="amber")]
        ),
    )
    # real _report_params(json.dumps([m.model_dump()...])) did not crash
    assert updated is not None
