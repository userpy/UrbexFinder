from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import application.workers.handlers.handle_places_bootstrap as bootstrap_module
from infrastructure.messaging.rabbitmq.constants import (
    PLACES_BOOTSTRAP_ROUTING_KEY,
)


def _settings():
    return SimpleNamespace(
        seed_places=False,
        admin_name="admin",
        admin_id="1",
        postgres_user="test",
        postgres_password="test",
        postgres_db="telegram_bot_test",
        postgres_host="test-db",
        postgres_port=5432,
        elasticsearch_host="http://elasticsearch:9200",
        elasticsearch_user="elastic",
        elasticsearch_password="test",
        kmz_path="geo_data/places.kmz",
        csv_path="geo_data/places.csv",
    )


async def test_bootstrap_rejects_unknown_routing_key():
    with pytest.raises(ValueError, match="Unsupported routing key"):
        await bootstrap_module.handle_places_bootstrap(
            {},
            "places.unknown",
            settings=_settings(),
        )


async def test_bootstrap_rejects_non_boolean_seed_flag():
    with pytest.raises(ValueError, match="seed_places must be a boolean"):
        await bootstrap_module.handle_places_bootstrap(
            {"seed_places": "yes"},
            PLACES_BOOTSTRAP_ROUTING_KEY,
            settings=_settings(),
        )


async def test_bootstrap_runs_steps_and_closes_resources(monkeypatch):
    database = SimpleNamespace(
        connect=AsyncMock(),
        close=AsyncMock(),
    )
    indexer = SimpleNamespace(close=AsyncMock())

    seed_places = AsyncMock()
    deduplicate_places = AsyncMock()
    update_addresses = AsyncMock()
    reindex_places = AsyncMock()

    monkeypatch.setattr(
        bootstrap_module,
        "AsyncDatabase",
        lambda **kwargs: database,
    )
    monkeypatch.setattr(
        bootstrap_module,
        "ElasticPlacesIndexer",
        lambda **kwargs: indexer,
    )
    monkeypatch.setattr(
        bootstrap_module,
        "seed_places_from_kml",
        seed_places,
    )
    monkeypatch.setattr(
        bootstrap_module,
        "deduplicate_places",
        deduplicate_places,
    )
    monkeypatch.setattr(
        bootstrap_module,
        "update_place_full_addres",
        update_addresses,
    )
    monkeypatch.setattr(
        bootstrap_module,
        "indexing_places_elastic_search",
        reindex_places,
    )

    await bootstrap_module.handle_places_bootstrap(
        {"seed_places": True},
        PLACES_BOOTSTRAP_ROUTING_KEY,
        settings=_settings(),
    )

    database.connect.assert_awaited_once()
    seed_places.assert_awaited_once_with(
        database,
        "geo_data/places.kmz",
        True,
    )
    deduplicate_places.assert_awaited_once_with(database)
    update_addresses.assert_awaited_once_with(
        database,
        "geo_data/places.csv",
    )
    reindex_places.assert_awaited_once_with(
        indexer,
        close_indexer=False,
    )
    indexer.close.assert_awaited_once()
    database.close.assert_awaited_once()
