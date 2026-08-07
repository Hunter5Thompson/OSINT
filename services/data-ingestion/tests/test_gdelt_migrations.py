from unittest.mock import AsyncMock, MagicMock

import pytest

from gdelt_raw.migrations.apply import (
    SOURCE_DUP_PREFLIGHT_QUERY,
    apply_phase2,
    read_cypher_file,
)


def test_phase1_file_contains_expected_constraints():
    text = read_cypher_file("phase1_constraints.cypher")
    assert "gdelt_event_id_unique" in text
    assert "gdelt_doc_id_unique" in text
    assert "source_name_unique" in text
    assert "theme_code_unique" in text
    assert "GDELTEvent" in text
    assert "GDELTDocument" in text


def test_phase2_file_contains_indexes():
    text = read_cypher_file("phase2_indexes.cypher")
    assert "event_source_date" in text
    assert "event_cameo_root" in text
    assert "location_geo" not in text  # consolidated into the Plan-06A migration


def test_source_preflight_query_is_parameterless():
    assert "name, count" in SOURCE_DUP_PREFLIGHT_QUERY or \
           "count(*)" in SOURCE_DUP_PREFLIGHT_QUERY


@pytest.mark.asyncio
async def test_phase2_runner_applies_gdelt_and_spatial_indexes() -> None:
    session = MagicMock(run=AsyncMock())
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)
    driver = MagicMock()
    driver.session.return_value = session_context

    await apply_phase2(driver)

    statements = [call.args[0] for call in session.run.await_args_list]
    assert any("event_source_date" in statement for statement in statements)
    assert any("location_country_scope_derivation" in statement for statement in statements)
    assert any("location_admin1_scope_derivation" in statement for statement in statements)
    assert any("location_admin2_scope_derivation" in statement for statement in statements)
    assert any("location_geo" in statement for statement in statements)
