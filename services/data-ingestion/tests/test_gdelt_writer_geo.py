from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gdelt_raw.schemas import GDELTEventWrite
from gdelt_raw.writers.neo4j_writer import MERGE_LOCATION, Neo4jWriter, location_params_for
from graph_integrity.spatial_normalizer import load_normalization_index

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CATALOG_DIRECTORY = (
    REPOSITORY_ROOT
    / "services/backend/data/spatial/catalogs/spatial-v1-e76a16bff799"
)
CROSSWALK_PATH = (
    REPOSITORY_ROOT
    / "services/data-ingestion/spatial_catalog/data/country_crosswalk.json"
)


@pytest.fixture(scope="module")
def spatial_index():
    return load_normalization_index(
        CATALOG_DIRECTORY,
        crosswalk_path=CROSSWALK_PATH,
    )


def _event(**overrides: object) -> GDELTEventWrite:
    values: dict[str, object] = {
        "event_id": "gdelt:event:1",
        "cameo_code": "193",
        "cameo_root": 19,
        "quad_class": 4,
        "goldstein": -6.5,
        "avg_tone": -4.0,
        "num_mentions": 3,
        "num_sources": 2,
        "num_articles": 3,
        "date_added": "2026-06-13T22:15:00Z",
        "fraction_date": 2026.4,
        "source_url": "https://example.test/event",
        "codebook_type": "conflict.armed",
        "filter_reason": "tactical",
        "action_geo_lat": 48.0,
        "action_geo_long": 37.8,
        "action_geo_fullname": "Donetsk, Ukraine",
        "action_geo_country_code": "UP",
        "action_geo_feature_id": "-1044367",
    }
    values.update(overrides)
    return GDELTEventWrite.model_validate(values)


def test_merge_location_writes_geo_and_all_spatial_fields_with_parameters() -> None:
    assert "MERGE (l:Location {loc_key: $loc_key})" in MERGE_LOCATION
    assert "MERGE (ev)-[:OCCURRED_AT]->(l)" in MERGE_LOCATION
    assert "point({longitude: $longitude, latitude: $latitude})" in MERGE_LOCATION
    for field in (
        "source_country_code",
        "source_country_code_system",
        "country_iso3",
        "admin1_code",
        "admin2_code",
        "country_scope_key",
        "admin1_scope_key",
        "admin2_scope_key",
        "spatial_basis",
        "spatial_precision",
        "spatial_catalog_revision",
        "spatial_derivation_revision",
        "spatial_conflict",
        "spatial_conflict_scope_keys",
    ):
        assert f"l.{field} = ${field}" in MERGE_LOCATION
    assert "spatial-v1-e76a16bff799" not in MERGE_LOCATION
    assert "country:UKR" not in MERGE_LOCATION


def test_location_params_normalizes_gdelt_action_geo(spatial_index) -> None:
    params = location_params_for(_event(), spatial_index)

    assert params is not None
    assert params["loc_key"] == "gdelt:loc:-1044367"
    assert params["event_id"] == "gdelt:event:1"
    assert params["name"] == "Donetsk, Ukraine"
    assert params["country"] == "UP"
    assert params["latitude"] == 48.0
    assert params["longitude"] == 37.8
    assert params["source_country_code"] == "UP"
    assert params["source_country_code_system"] == "gdelt-gec"
    assert params["country_scope_key"] == "country:UKR"
    assert params["admin1_scope_key"] == "admin1:iso3166-2:UA-14"
    assert params["spatial_catalog_revision"] == "spatial-v1-e76a16bff799"
    assert params["spatial_derivation_revision"] == "spatial-derive-v1-4d1de888e0c7"
    assert params["spatial_conflict"] is False


def test_location_params_supports_country_only_without_invented_point(spatial_index) -> None:
    params = location_params_for(
        _event(
            action_geo_lat=None,
            action_geo_long=None,
            action_geo_fullname="Ukraine",
            action_geo_feature_id=None,
        ),
        spatial_index,
    )

    assert params is not None
    assert params["country_scope_key"] == "country:UKR"
    assert params["admin1_scope_key"] is None
    assert params["latitude"] is None
    assert params["longitude"] is None
    assert params["spatial_precision"] == "country"


def test_location_params_preserves_real_zero_zero_when_source_has_identity(
    spatial_index,
) -> None:
    params = location_params_for(
        _event(
            action_geo_lat=0.0,
            action_geo_long=0.0,
            action_geo_fullname="Gulf of Guinea",
            action_geo_country_code=None,
            action_geo_feature_id="ocean-grid-0-0",
        ),
        spatial_index,
    )

    assert params is not None
    assert params["latitude"] == 0.0
    assert params["longitude"] == 0.0
    assert params["spatial_precision"] == "point"


def test_location_params_marks_source_coordinate_contradiction(spatial_index) -> None:
    params = location_params_for(
        _event(
            action_geo_lat=37.0,
            action_geo_long=-95.0,
            action_geo_fullname="Kansas, United States",
        ),
        spatial_index,
    )

    assert params is not None
    assert params["country_scope_key"] == "country:UKR"
    assert params["spatial_conflict"] is True
    assert params["spatial_conflict_scope_keys"] == ["country:UKR", "country:USA"]


def test_location_params_none_without_any_stable_location_identity(spatial_index) -> None:
    assert (
        location_params_for(
            _event(
                action_geo_lat=None,
                action_geo_long=None,
                action_geo_fullname=None,
                action_geo_country_code=None,
                action_geo_feature_id=None,
            ),
            spatial_index,
        )
        is None
    )


def _writer_with_transaction(spatial_index, tx: MagicMock) -> Neo4jWriter:
    transaction_context = MagicMock()
    transaction_context.__aenter__ = AsyncMock(return_value=tx)
    transaction_context.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.begin_transaction = AsyncMock(return_value=transaction_context)
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)
    with patch("gdelt_raw.writers.neo4j_writer.AsyncGraphDatabase.driver"):
        writer = Neo4jWriter(
            "bolt://localhost:7687",
            "neo4j",
            "pw",
            spatial_index=spatial_index,
        )
    writer._driver = MagicMock()
    writer._driver.session.return_value = session_context
    return writer


@pytest.mark.asyncio
async def test_write_events_commits_event_and_location_in_one_transaction(
    spatial_index,
) -> None:
    tx = MagicMock(run=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())
    writer = _writer_with_transaction(spatial_index, tx)

    await writer.write_events([_event()])

    assert [call.args[0] for call in tx.run.await_args_list][-1] == MERGE_LOCATION
    tx.commit.assert_awaited_once()
    tx.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_events_rolls_back_when_location_write_fails(spatial_index) -> None:
    tx = MagicMock(
        run=AsyncMock(side_effect=[None, RuntimeError("location write failed")]),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    writer = _writer_with_transaction(spatial_index, tx)

    with pytest.raises(RuntimeError, match="location write failed"):
        await writer.write_events([_event()])

    tx.rollback.assert_awaited_once()
    tx.commit.assert_not_awaited()
