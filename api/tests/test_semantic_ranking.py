import httpx

from urbex.infrastructure import osint_evidence
from urbex.infrastructure.semantic_ranking import rank_candidates
from urbex.infrastructure.osint_identity import verify_source


class _Response:
    def __init__(self, scores):
        self._scores = scores

    def raise_for_status(self):
        return None

    def json(self):
        return {'scores': self._scores}


class _Client:
    scores = []

    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, _url, json):
        assert json['query']
        assert len(json['documents']) == len(self.scores)
        return _Response(self.scores)


def test_rank_candidates_uses_reranker_then_embedding_scores(monkeypatch):
    candidates = [
        {'title': 'First', 'url': 'https://example.test/first', 'snippet': 'one'},
        {'title': 'Second', 'url': 'https://example.test/second', 'snippet': 'two'},
    ]
    _Client.scores = [
        {'embedding_score': 0.9, 'reranker_score': 0.2},
        {'embedding_score': 0.4, 'reranker_score': 0.8},
    ]
    monkeypatch.setattr(httpx, 'Client', _Client)

    result = rank_candidates(
        'http://semantic:8100',
        {'name': 'Abandoned place', 'full_address': 'Moscow'},
        candidates,
    )

    assert [row['title'] for row in result] == ['Second', 'First']
    assert result[0]['reranker_score'] == 0.8
    assert result[1]['embedding_score'] == 0.9
    assert candidates[0] == {
        'title': 'First', 'url': 'https://example.test/first', 'snippet': 'one',
    }


def test_rank_candidates_falls_back_to_search_order_on_service_error(monkeypatch):
    class FailedClient(_Client):
        def post(self, *_args, **_kwargs):
            raise httpx.ConnectError('offline')

    monkeypatch.setattr(httpx, 'Client', FailedClient)
    candidates = [
        {'title': 'First', 'url': 'https://example.test/first'},
        {'title': 'Second', 'url': 'https://example.test/second'},
    ]

    assert rank_candidates('http://semantic:8100', {'name': 'Place'}, candidates) is candidates


def test_enrichment_fetch_order_uses_semantic_rank(monkeypatch):
    fetched = []

    class OrderedPool:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def map(self, function, urls):
            return [function(url) for url in urls]

    def fake_fetch(url):
        fetched.append(url)
        return None

    monkeypatch.setattr(osint_evidence, '_fetch', fake_fetch)
    monkeypatch.setattr(osint_evidence, 'ThreadPoolExecutor', OrderedPool)
    place = {'name': 'Unknown place'}
    candidates = [
        {'title': f'Candidate {index}', 'url': f'https://wikimapia.org/{index}',
         'reranker_score': score}
        for index, score in enumerate((0.2, 0.9, 0.4, 0.3))
    ]

    osint_evidence.enrich_candidates(place, candidates, [])

    assert fetched == [
        'https://wikimapia.org/1',
        'https://wikimapia.org/2',
        'https://wikimapia.org/3',
        'https://wikimapia.org/0',
    ]


def test_semantic_score_does_not_confirm_source_identity():
    place = {'name': 'Abandoned hospital', 'full_address': 'Moscow'}
    candidate = {
        'title': 'Abandoned hospital in Moscow',
        'url': 'https://example.test/hospital',
        'reranker_score': 1.0,
        'embedding_score': 1.0,
    }

    assert verify_source(place, candidate).status == 'unconfirmed'
