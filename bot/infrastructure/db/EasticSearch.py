from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk, async_scan
from loguru import logger

from infrastructure.db.PgDb import AsyncDatabase


DEFAULT_INDEX_NAME = "urbex_places_v1"
LEGACY_INDEX_NAME = "places"
BATCH_SIZE = 500

# Keep in sync with api/infrastructure/search/elasticsearch.py INDEX_BODY.
INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "id": {"type": "integer"},
            **{
                field: {"type": "text", "analyzer": "russian"}
                for field in (
                    "name",
                    "description",
                    "full_address",
                    "region",
                    "category",
                )
            },
        },
    },
}


def _create_client(
    es_url,
    es_user,
    es_password,
) -> AsyncElasticsearch:
    if es_password:
        return AsyncElasticsearch(es_url, basic_auth=(es_user, es_password))
    return AsyncElasticsearch(es_url)


class ElasticPlacesIndexer:
    def __init__(
        self,
        db: AsyncDatabase = None,
        es_url: str = None,
        es_user: str = None,
        es_password: str = None,
        index_name: str | None = None,
    ):
        self.db = db
        self.index = (index_name or DEFAULT_INDEX_NAME).strip() or DEFAULT_INDEX_NAME
        self.es = _create_client(es_url=es_url, es_user=es_user, es_password=es_password)

    def to_bulk_actions(self, rows):
        """Генерирует документы для bulk"""
        for row in rows:
            yield {
                "_op_type": "index",
                "_index": self.index,
                "_id": row["id"],
                "_source": {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row.get("description"),
                    "category": row.get("category"),
                    "full_address": row.get("full_address"),
                    "region": row.get("region") or "Не указан",
                },
            }

    async def reindex(self):
        """Полная индексация всех мест из PostgreSQL в Elasticsearch.
        При необходимости создаёт индекс автоматически.
        """
        exists = await self.es.indices.exists(index=self.index)
        if not exists:
            await self.es.indices.create(index=self.index, body=INDEX_BODY)
            logger.info(f"Created index '{self.index}'")
        else:
            logger.info(f"Index '{self.index}' already exists")

        indexed_count = 0
        offset = 0
        pg_ids: set[int] = set()
        while True:
            rows = await self.db.places.get_places(limit=BATCH_SIZE, offset=offset)
            if not rows:
                break

            await async_bulk(self.es, self.to_bulk_actions(rows))
            pg_ids.update(row["id"] for row in rows)
            indexed_count += len(rows)
            offset += BATCH_SIZE
            logger.info(f"Indexed {indexed_count} places")

        deleted_count = await self._delete_stale_documents(pg_ids)
        logger.info(f"Deleted {deleted_count} stale places from index")
        await self._delete_legacy_index()

    async def _delete_legacy_index(self) -> None:
        """Drop the old bot-only index after switching to the shared API index."""
        if self.index == LEGACY_INDEX_NAME:
            return
        try:
            exists = await self.es.indices.exists(index=LEGACY_INDEX_NAME)
            if not exists:
                return
            await self.es.indices.delete(index=LEGACY_INDEX_NAME)
            logger.info("Deleted legacy Elasticsearch index {!r}", LEGACY_INDEX_NAME)
        except Exception as exc:
            # 404 = already gone (race with another worker); anything else is non-fatal.
            status = getattr(exc, "status_code", None) or getattr(exc, "meta", None) and getattr(exc.meta, "status", None)
            if status == 404:
                return
            logger.warning(
                "Could not delete legacy Elasticsearch index {!r}: {}",
                LEGACY_INDEX_NAME,
                exc,
            )

    async def _iter_es_ids(self):
        """Итерирует по id документов из Elasticsearch."""
        async for hit in async_scan(
            self.es,
            index=self.index,
            query={"_source": False, "query": {"match_all": {}}},
        ):
            doc_id = hit.get("_id")
            if doc_id is None:
                continue
            try:
                yield int(doc_id)
            except (TypeError, ValueError):
                continue

    async def _delete_stale_documents(self, pg_ids: set[int]) -> int:
        """Удаляет из индекса документы, которых больше нет в PostgreSQL."""
        es_ids: set[int] = set()
        async for doc_id in self._iter_es_ids():
            es_ids.add(doc_id)

        stale_ids = es_ids - pg_ids
        if not stale_ids:
            return 0

        def stale_actions():
            for stale_id in stale_ids:
                yield {
                    "_op_type": "delete",
                    "_index": self.index,
                    "_id": stale_id,
                }

        await async_bulk(self.es, stale_actions())
        return len(stale_ids)

    async def search_place_ids(self, query: str) -> list[int]:
        """
        Ищет в Elasticsearch места по ключевому слову и возвращает только id
        """
        resp = await self.es.search(
            index=self.index,
            body={
              "_source": ["id"],
              "size": 1000,
              "query": {
                "bool": {
                  "should": [
                    {
                      "multi_match": {
                        "query": query,
                        "type": "phrase",
                        "fields": ["name^6", "full_address^3", "region^2"],
                        "slop": 3
                      }
                    },
                    {
                      "multi_match": {
                        "query": query,
                        "type": "cross_fields",
                        "fields": ["name^4", "full_address^2", "region^2", "description", "category"],
                        "operator": "and"
                      }
                    },
                    {
                      "multi_match": {
                        "query": query,
                        "type": "best_fields",
                        "fields": ["name^3", "full_address^2", "region^2", "description", "category"],
                        "operator": "and",
                        "fuzziness": "AUTO",
                        "prefix_length": 2
                      }
                    }
                  ],
                  "minimum_should_match": 1
                }
              }
            }
        )

        ids = [hit["_source"]["id"] for hit in resp["hits"]["hits"]]
        return ids

    async def close(self):
        """Закрывает соединение с Elasticsearch"""
        await self.es.close()
