from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk, async_scan

from infrastructure.db.PgDb import AsyncDatabase


INDEX_NAME = "places"
BATCH_SIZE = 500


def _create_client(
    es_url,
    es_user,
    es_password,
) -> AsyncElasticsearch:
    if es_password:
        return AsyncElasticsearch(es_url, basic_auth=(es_user, es_password))
    return AsyncElasticsearch(es_url)


class ElasticPlacesIndexer:
    INDEX_BODY = {
        "mappings": {
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "text"},
                "description": {"type": "text"},
                "category": {"type": "keyword"},
                "full_address": {"type": "text"},
            }
        }
    }

    def __init__(
        self,
        db: AsyncDatabase = None,
        es_url: str = None,
        es_user: str = None,
        es_password: str = None,
    ):
        self.db = db
        self.es = _create_client(es_url=es_url, es_user=es_user, es_password=es_password)

    def to_bulk_actions(self, rows):
        """Генерирует документы для bulk"""
        for row in rows:
            yield {
                "_op_type": "index",
                "_index": INDEX_NAME,
                "_id": row["id"],
                "_source": {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "category": row["category"],
                    "full_address": row["full_address"],
                },
            }

    async def reindex(self):
        """Полная индексация всех мест из PostgreSQL в Elasticsearch.
        При необходимости создаёт индекс автоматически.
        """
        # создаём индекс, если его ещё нет
        exists = await self.es.indices.exists(index=INDEX_NAME)
        if not exists:
            await self.es.indices.create(index=INDEX_NAME, body=self.INDEX_BODY)
            print(f"Created index '{INDEX_NAME}'")
        else:
            print(f"Index '{INDEX_NAME}' already exists")

        # bulk индексация
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
            print(f"Indexed {indexed_count} places")

        deleted_count = await self._delete_stale_documents(pg_ids)
        print(f"Deleted {deleted_count} stale places from index")

    async def _iter_es_ids(self):
        """Итерирует по id документов из Elasticsearch."""
        async for hit in async_scan(
            self.es,
            index=INDEX_NAME,
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
                    "_index": INDEX_NAME,
                    "_id": stale_id,
                }

        await async_bulk(self.es, stale_actions())
        return len(stale_ids)


    async def search_place_ids(self, query: str) -> list[int]:
        """
        Ищет в Elasticsearch места по ключевому слову и возвращает только id
        """
        # Elasticsearch search
        resp = await self.es.search(
            index=INDEX_NAME,
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
                        "fields": ["name^6", "full_address^3"],
                        "slop": 3
                      }
                    },
                    {
                      "multi_match": {
                        "query": query,
                        "type": "cross_fields",
                        "fields": ["name^4", "full_address^2", "description", "category"],
                        "operator": "and"
                      }
                    },
                    {
                      "multi_match": {
                        "query": query,
                        "type": "best_fields",
                        "fields": ["name^3", "full_address^2", "description", "category"],
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

        # Составляем список id
        ids = [hit["_source"]["id"] for hit in resp["hits"]["hits"]]
        return ids

    async def close(self):
        """Закрывает соединение с Elasticsearch"""
        await self.es.close()
