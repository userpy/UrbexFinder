"""Elasticsearch text retrieval, with PostgreSQL as the authority on visibility.

Use HTTP to match the existing Elasticsearch 7 cluster without a conflicting
major-version Python SDK. No browser request talks directly to Elasticsearch.
"""
import json
import re
import httpx
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from urbex.domain.rules import DomainError

TEXT_FIELDS = ['name^6', 'full_address^3', 'region^2', 'category^2', 'description']
INDEX_BODY = {
    'settings': {'number_of_shards': 1, 'number_of_replicas': 0},
    'mappings': {'dynamic': 'strict', 'properties': {
        'id': {'type': 'integer'},
        **{field: {'type': 'text', 'analyzer': 'russian'} for field in
           ('name', 'description', 'full_address', 'region', 'category')},
    }},
}


class ElasticSearch:
    def __init__(self, config, engine):
        self.engine = engine
        self.url = config.elasticsearch_url.rstrip('/')
        self.index = config.elasticsearch_index
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', self.index):
            raise ValueError('Invalid Elasticsearch index name')
        self.auth = (config.elasticsearch_user, config.elasticsearch_password) if config.elasticsearch_password else None

    def client(self):
        if not self.url:
            raise DomainError('Поисковый сервис не настроен', 503)
        return httpx.Client(base_url=self.url, auth=self.auth, timeout=30, follow_redirects=False)

    @staticmethod
    def request(client, method, path, **kwargs):
        try:
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            result = response.json()
            if result.get('timed_out') or result.get('_shards', {}).get('failed', 0):
                raise ValueError('Incomplete search result')
            return result
        except (httpx.HTTPError, ValueError):
            raise DomainError('Поиск временно недоступен. Попробуйте позже.', 503) from None

    def ensure_index(self, client, connection):
        try:
            response = client.head('/'+self.index)
            if response.status_code == 404:
                self.request(client, 'PUT', '/'+self.index, json=INDEX_BODY)
                # Also recover from an index/volume being lost after successful sync.
                connection.execute(text('INSERT INTO web_search_outbox(place_id) SELECT id FROM places ON CONFLICT DO NOTHING'))
            else:
                response.raise_for_status()
        except httpx.HTTPError:
            raise DomainError('Поиск временно недоступен. Попробуйте позже.', 503) from None

    def sync(self):
        """At-least-once, idempotent delivery; failed bulk items keep the queue.

        The revision comparison protects updates committed during a bulk request.
        The advisory lock prevents multiple API workers from racing in ES.
        """
        processed = 0
        with self.client() as client, self.engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '15s'"))
            try:
                connection.execute(text('SELECT pg_advisory_xact_lock(739130067)'))
            except OperationalError:
                raise DomainError('Поисковый индекс обновляется. Попробуйте позже.', 503) from None
            self.ensure_index(client, connection)
            while True:
                rows = connection.execute(text('''SELECT q.place_id, q.revision, p.id,
                    p.name, p.description, p.full_address, p.region, p.category,
                    p.status, p.nonexistent_reports_count
                    FROM web_search_outbox q LEFT JOIN places p ON p.id=q.place_id
                    ORDER BY q.place_id LIMIT 1000''')).mappings().all()
                if not rows:
                    break
                lines = []
                for row in rows:
                    public = row['id'] is not None and row['status'] == 'published' and row['nonexistent_reports_count'] < 10
                    action = 'index' if public else 'delete'
                    lines.append(json.dumps({action: {'_index': self.index, '_id': str(row['place_id'])}}))
                    if public:
                        lines.append(json.dumps({key: row[key] for key in
                            ('id','name','description','full_address','region','category')}, ensure_ascii=False))
                result = self.request(client, 'POST', '/_bulk', content=('\n'.join(lines)+'\n').encode(),
                    headers={'Content-Type': 'application/x-ndjson'}, params={'refresh': 'true'})
                if len(result.get('items', [])) != len(rows):
                    raise DomainError('Не удалось обновить поисковый индекс', 503)
                for item in result['items']:
                    operation, status = next(iter(item.items()))
                    if status['status'] >= 300 and not (operation == 'delete' and status['status'] == 404):
                        raise DomainError('Не удалось обновить поисковый индекс', 503)
                connection.execute(text('DELETE FROM web_search_outbox WHERE place_id=:place_id AND revision=:revision'),
                    [{'place_id': r['place_id'], 'revision': r['revision']} for r in rows])
                processed += len(rows)
        return processed

    def ids(self, query, search_in='all'):
        fields = {'name': ['name'], 'address': ['full_address', 'region'], 'description': ['description']}.get(search_in, TEXT_FIELDS)
        # PIT + search_after reads every match, including beyond ES's 10k window.
        # Only IDs leave ES; PostgreSQL performs final filtering and pagination.
        with self.client() as client:
            pit = self.request(client, 'POST', f'/{self.index}/_pit', params={'keep_alive': '1m'})['id']
            ids, after = [], None
            try:
                while True:
                    body = {
                        'size': 1000, '_source': False, 'track_total_hits': False,
                        'pit': {'id': pit, 'keep_alive': '1m'},
                        'sort': [{'_score': 'desc'}, {'id': 'asc'}],
                        'query': {'bool': {'minimum_should_match': 1, 'should': [
                            {'multi_match': {'query': query, 'fields': fields, 'type': 'phrase', 'boost': 3}},
                            {'multi_match': {'query': query, 'fields': fields, 'operator': 'and',
                                             'fuzziness': 'AUTO', 'prefix_length': 1}},
                        ]}},
                    }
                    if after is not None:
                        body['search_after'] = after
                    result = self.request(client, 'POST', '/_search', json=body)
                    pit = result.get('pit_id', pit)
                    hits = result['hits']['hits']
                    if not hits:
                        break
                    ids.extend(int(hit['_id']) for hit in hits)
                    after = hits[-1]['sort']
                    if len(hits) < 1000:
                        break
                return ids
            finally:
                try:
                    client.request('DELETE', '/_pit', json={'id': pit})
                except httpx.HTTPError:
                    pass  # PIT expires; do not mask the original error.
