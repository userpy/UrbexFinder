from pathlib import Path

from loguru import logger

from infrastructure.db.PgDb import AsyncDatabase
from infrastructure.services.kmz_reader import KmzReader
from infrastructure.services.places_deduplicator import PlacesDeduplicationService
from infrastructure.db.EasticSearch import ElasticPlacesIndexer

APP_DIR = Path(__file__).resolve().parents[2]


async def seed_places_from_kml(db: AsyncDatabase, kml_path: str, is_run_seeding: bool):
    """Заполняет таблицу Places данными из KML, если таблица пуста"""
    if is_run_seeding:
        kmz = KmzReader(db=db, file_path=kml_path)
        await kmz.read()


async def update_place_full_addres(db: AsyncDatabase, csv_path: str):
    """Обновляет поле full_address в таблице Places данными из csv файла"""
    full_address_csv = Path(csv_path)
    if not full_address_csv.is_absolute():
        full_address_csv = APP_DIR / full_address_csv

    updated_count = await db.places.update_full_addresses_from_csv(full_address_csv)
    logger.info(f"[INFO] updated full_address from csv: {updated_count}")
    await db.places.update_all_full_addresses()


async def deduplicate_places(db: AsyncDatabase):
    """Дедупликация мест в таблице Places"""
    service = PlacesDeduplicationService(db=db)
    await service.run()


async def indexing_places_elastic_search(indexer: ElasticPlacesIndexer):
    """Индексация мест в ElasticSearch"""
    await indexer.reindex()
    await indexer.close()
