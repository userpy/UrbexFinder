from infrastructure.db.PgDb import AsyncDatabase
from infrastructure.services.kmz_reader import KmzReader
from infrastructure.services.places_deduplicator import PlacesDeduplicationService
from infrastructure.db.EasticSearch import ElasticPlacesIndexer

async def seed_places_from_kml(db: AsyncDatabase, kml_path: str):
    """Заполняет таблицу Places данными из KML, если таблица пуста"""
    kmz = KmzReader(db=db, file_path=kml_path)
    await kmz.read()


async def update_place_full_addres(db: AsyncDatabase):
    await db.places.update_all_full_addresses()


async def deduplicate_places(db: AsyncDatabase):
    service = PlacesDeduplicationService(db=db)
    await service.run()


async def indexing_places_elastic_search(indexer: ElasticPlacesIndexer):
    await indexer.reindex()
    await indexer.close()
