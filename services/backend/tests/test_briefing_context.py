# services/backend/tests/test_briefing_context.py
from app.models.almanac import (
    AlmanacCapital,
    AlmanacFact,
    AlmanacFacts,
    AlmanacSignalItem,
    CountryAlmanac,
)
from app.services.briefing import RESEARCH_ALIASES, build_briefing_context


def _country(**kw):
    base = dict(
        id="276", iso3="DEU", m49="276", name="Germany", region="Europe",
        subregion="Western Europe", capital=AlmanacCapital(name="Berlin", lat=52.5, lon=13.4),
        facts=AlmanacFacts(
            government=[AlmanacFact(label="Chief of state", value="President X")],
            economy=[AlmanacFact(label="Real GDP", value="$5T")],
            security=[AlmanacFact(label="Military", value="Bundeswehr")],
        ),
        updated_at="2026-05-17", source_note="CIA World Factbook",
    )
    base.update(kw)
    return CountryAlmanac(**base)


def _signal(title="Border incident", event_id="e1"):
    return AlmanacSignalItem(
        event_id=event_id, ts="2026-06-01T10:00:00Z", type="signal.rss",
        title=title, severity="high", source="reuters", url="http://x",
    )


def test_task_is_short_and_names_canonical_identity():
    ctx = build_briefing_context(
        _country(), [_signal()], factbook_revision="abc", refreshed_at="2026-05-17",
    )
    assert len(ctx.task) <= 800
    assert "Germany" in ctx.task and "DEU" in ctx.task and "276" in ctx.task


def test_context_is_delimited_and_budgeted():
    ctx = build_briefing_context(
        _country(), [_signal()],
        factbook_revision="abc", refreshed_at="2026-05-17", budget_chars=4000,
    )
    assert ctx.grounding_context.startswith("<<<GROUNDING_DATA")
    assert ctx.grounding_context.rstrip().endswith(">>>END_GROUNDING_DATA")
    assert len(ctx.grounding_context) <= 4000
    assert "Border incident" in ctx.grounding_context


def test_evidence_items_are_bounded_and_allowlisted():
    long_title = "T" * 500
    ctx = build_briefing_context(_country(), [_signal(title=long_title, event_id="e9")],
                                 factbook_revision="rev1", refreshed_at="2026-05-17")
    almanac = ctx.grounding_evidence[0]
    assert almanac["source_type"] == "dataset"
    assert almanac["provider"] == "odin-country-almanac"
    assert almanac["doc_id"] == "odin-country-almanac:rev1:2026-05-17:DEU"
    assert "CIA World Factbook" in almanac["content"]
    sig = ctx.grounding_evidence[1]
    assert sig["provider"] == "odin-live-signal"
    assert sig["doc_id"] == "odin-signal:e9"
    assert len(sig["title"]) <= 300            # external title clamped
    assert "published_at" not in sig
    assert "observation_time" in sig["content"]
    assert len(ctx.grounding_evidence) <= 6


def test_no_signals_states_it_and_aliases_resolve_by_name():
    stub = _country(iso3=None, id="N. Cyprus", m49="N. Cyprus", name="N. Cyprus",
                    facts=AlmanacFacts(), source_note="REST Countries (no Factbook profile)")
    ctx = build_briefing_context(stub, [], factbook_revision="rev1", refreshed_at="2026-05-17")
    ctx_lower = ctx.grounding_context.lower()
    assert "keine aktiven Signale" in ctx_lower or "keine signale" in ctx_lower
    assert "TRNC" in ctx.task               # alias via name key
    assert RESEARCH_ALIASES["N. Cyprus"] == ["Northern Cyprus", "TRNC"]


def test_long_facts_are_trimmed_whole_line_and_signal_block_survives():
    # Iran-scale: security alone ~4700 chars across many facts. Facts must trim by
    # whole lines and the signal status must still appear.
    huge = CountryAlmanac(
        id="364", iso3="IRN", m49="364", name="Iran", region="Asia", subregion="Southern Asia",
        capital=AlmanacCapital(name="Tehran", lat=35.7, lon=51.4),
        facts=AlmanacFacts(
            security=[AlmanacFact(label=f"S{i}", value="x" * 200) for i in range(30)],
        ),
        updated_at="2026-05-17", source_note="CIA World Factbook",
    )
    ctx = build_briefing_context(
        huge, [_signal(title="Drohnenangriff", event_id="ir1")],
        factbook_revision="r", refreshed_at="2026-05-17", budget_chars=4000,
    )
    assert len(ctx.grounding_context) <= 4000
    assert "Active ODIN signals" in ctx.grounding_context          # signal block not displaced
    assert "Drohnenangriff" in ctx.grounding_context
    assert "x" * 200 in ctx.grounding_context                      # kept facts are whole lines
    # no partial fact line: every "- S" line that appears is complete
    for line in ctx.grounding_context.splitlines():
        if line.startswith("- S"):
            assert line.endswith("x" * 200)


def test_truncate_message_marks_when_cut():
    from app.services.briefing import truncate_message
    assert truncate_message("short") == "short"
    out = truncate_message("y" * 9000, limit=8000)
    assert len(out) == 8000 and out.endswith("…[gekürzt]")


def test_five_long_signal_titles_stay_within_budget():
    sigs = [_signal(title="L" * 1000, event_id=f"s{i}") for i in range(5)]
    ctx = build_briefing_context(
        _country(), sigs, factbook_revision="r", refreshed_at="2026-05-17", budget_chars=4000,
    )
    assert len(ctx.grounding_context) <= 4000          # capped signal titles can't blow the budget
    assert "Active ODIN signals" in ctx.grounding_context


def test_long_facts_keep_source_note_provenance():
    huge = CountryAlmanac(
        id="364", iso3="IRN", m49="364", name="Iran", region="Asia", subregion="S", capital=None,
        facts=AlmanacFacts(
            security=[AlmanacFact(label=f"S{i}", value="x" * 300) for i in range(20)],
        ),
        updated_at="2026-05-17", source_note="CIA World Factbook",
    )
    almanac = build_briefing_context(
        huge, [], factbook_revision="r", refreshed_at="2026-05-17",
    ).grounding_evidence[0]
    assert len(almanac["content"]) <= 2000
    assert almanac["content"].endswith("Quelle: CIA World Factbook")   # provenance never displaced


def test_long_signal_title_keeps_observation_time():
    sig = build_briefing_context(
        _country(), [_signal(title="T" * 5000, event_id="big")],
        factbook_revision="r", refreshed_at="2026-05-17",
    ).grounding_evidence[1]
    assert len(sig["content"]) <= 2000
    assert "observation_time:" in sig["content"]          # metadata never displaced by a long title


def test_long_signal_type_stays_within_content_bound():
    # Redis codebook_type is unbounded (signal_stream.py:108) — an overlong type must not
    # blow _CONTENT_MAX, which would make Intelligence reject the GroundingEvidenceItem.
    huge_type = AlmanacSignalItem(
        event_id="t1", ts="2026-06-01T10:00:00Z", type="x" * 5000,
        title="short", severity="high", source="reuters", url="",
    )
    out = build_briefing_context(
        _country(), [huge_type], factbook_revision="r", refreshed_at="2026-05-17",
    ).grounding_evidence[1]
    assert len(out["content"]) <= 2000
    assert "observation_time:" in out["content"]


def test_pathological_country_name_stays_within_budget():
    ctx = build_briefing_context(
        _country(name="N" * 6000), [_signal(title="X" * 1000, event_id="z1")],
        factbook_revision="r", refreshed_at="2026-05-17", budget_chars=4000,
    )
    assert len(ctx.grounding_context) <= 4000
    assert ctx.grounding_context.startswith("<<<GROUNDING_DATA")
    assert ctx.grounding_context.rstrip().endswith(">>>END_GROUNDING_DATA")


def test_doc_id_is_bounded_to_200():
    ctx = build_briefing_context(_country(), [_signal()],
                                 factbook_revision="R" * 500, refreshed_at="F" * 500)
    assert len(ctx.grounding_evidence[0]["doc_id"]) <= 200
    assert len(ctx.grounding_evidence[1]["doc_id"]) <= 200
