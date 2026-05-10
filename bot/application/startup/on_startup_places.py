from pathlib import Path

from loguru import logger

from infrastructure.db.PgDb import AsyncDatabase
from infrastructure.services.kmz_reader import KmzReader
from infrastructure.services.places_deduplicator import PlacesDeduplicationService
from infrastructure.db.EasticSearch import ElasticPlacesIndexer

DEFAULT_FULL_ADDRESS_CSV = Path(__file__).resolve().parents[2] / "geo_data" / "lat_lon_full_address.csv"


async def seed_places_from_kml(db: AsyncDatabase, kml_path: str, is_run_seeding: bool):
    """Заполняет таблицу Places данными из KML, если таблица пуста"""
    if is_run_seeding:
        kmz = KmzReader(db=db, file_path=kml_path)
        await kmz.read()


async def update_place_full_addres(db: AsyncDatabase):
    updated_count = await db.places.update_full_addresses_from_csv(DEFAULT_FULL_ADDRESS_CSV)
    logger.info(f"[INFO] updated full_address from csv: {updated_count}")
    await db.places.update_all_full_addresses()


async def deduplicate_places(db: AsyncDatabase):
    service = PlacesDeduplicationService(db=db)
    await service.run()


async def indexing_places_elastic_search(indexer: ElasticPlacesIndexer):
    await indexer.reindex()
    await indexer.close()
