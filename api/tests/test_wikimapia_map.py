import httpx
import pytest

from urbex.domain.rules import DomainError
from urbex.infrastructure import wikimapia_map as maps

POINT = (56.145, 37.4074)
PATH = '/z1/itiles/030/231/010/122/3.xy'
TILE = ('0302310101223|0|7\n'
        '123|100|374065000,374075000,561445000,561455000|14|516|'
        '!Узел связи\x1f Communication centre|1|polygon\n'
        '999|100|404065000,404075000,561445000,561455000|14|516|'
        '!Узел связи|1|polygon\n')


def mock_transport(monkeypatch, respond):
    monkeypatch.setattr(httpx, 'HTTPTransport', lambda **kwargs: httpx.MockTransport(respond))


def test_tile_address_and_nearby_primary_metadata():
    assert maps._tile_paths(*POINT) == [PATH]
    rows = maps._parse_tile(TILE, POINT)
    assert len(rows) == 1
    assert rows[0]['source_key'] == 'wikimapia.org:123'
    assert rows[0]['url'] == 'https://wikimapia.org/123/ru/'
    assert rows[0]['title'] == 'Узел связи'
    assert rows[0]['latitude'] == pytest.approx(56.145)
    assert rows[0]['longitude'] == pytest.approx(37.407)
    assert rows[0]['distance'] < 30


def test_tile_bounds_reject_invalid_rows_and_keep_valid_objects():
    body = TILE + ('42|1|nan,3,4,5|1||!Invalid|1|p\n'
                   '43|1|9999999999,9999999999,0,1|1||!Invalid|1|p\n'
                   '44|1|374075000,374065000,561445000,561455000|1||!Reversed|1|p\n')
    assert [r['source_key'] for r in maps._parse_tile(body, POINT)] == ['wikimapia.org:123']
    with pytest.raises(ValueError):
        maps._parse_tile('<html>upstream unavailable</html>', POINT)


def test_tile_boundary_requests_both_sides():
    # The prime meridian is a tile edge. Look on both sides of the point.
    assert 2 <= len(maps._tile_paths(56, 0)) <= 4
    assert len(maps._tile_paths(56, 179.9999)) <= 4


def test_map_follows_parent_tile_redirect_without_leaving_site(monkeypatch):
    calls = []
    def respond(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(301, headers={'location': '/z1/itiles/030/231/010/122.xy?old=path'})
        return httpx.Response(200, text=TILE)
    mock_transport(monkeypatch, respond)
    rows = maps.nearby_places(dict(zip(('latitude', 'longitude'), POINT)))
    assert len(rows) == 1
    assert calls == ['https://wikimapia.org' + PATH, 'https://wikimapia.org/z1/itiles/030/231/010/122.xy']


@pytest.mark.parametrize('target', [
    'http://127.0.0.1/private', 'https://wikimapia.org.evil.test/z1/itiles/030.xy',
    'https://wikimapia.org/api', 'https://user@wikimapia.org/z1/itiles/030.xy',
    'https://wikimapia.org:8080/z1/itiles/030.xy',
])
def test_map_rejects_redirects_outside_public_tile_endpoint(monkeypatch, target):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(302, headers={'location': target})
    mock_transport(monkeypatch, respond)
    with pytest.raises(DomainError):
        maps.nearby_places(dict(zip(('latitude', 'longitude'), POINT)))
    assert len(calls) == 1


@pytest.mark.parametrize('body', ['x' * 1_000_001, '<html>unavailable</html>'])
def test_map_bounds_response_size_and_reports_invalid_response(monkeypatch, body):
    mock_transport(monkeypatch, lambda request: httpx.Response(200, text=body))
    with pytest.raises(DomainError):
        maps.nearby_places(dict(zip(('latitude', 'longitude'), POINT)))


def test_invalid_coordinates_do_not_issue_requests(monkeypatch):
    monkeypatch.setattr(maps, '_fetch_tile', lambda *a: pytest.fail('Unexpected request'))
    assert maps.nearby_places({'latitude': 91, 'longitude': 37}) == []
    assert maps.nearby_places({'latitude': None, 'longitude': 37}) == []
