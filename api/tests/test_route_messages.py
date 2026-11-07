import json
import httpx
import pytest
from urbex.domain.rules import DomainError
from urbex.infrastructure.telegram import route_messages, send_route


def route(count=1, name='Карьер <&>'):
    return {'name': 'Поездка <&>', 'trip_date': '2026-11-07', 'items': [
        {'status': 'planned', 'place': {'name': f'{i} {name}',
         'latitude': 55.123456, 'longitude': 37.654321, 'full_address': 'Москва & область'}}
        for i in range(count)]}


def test_card_has_safe_html_coordinates_and_map():
    message, = route_messages(route())
    assert 'Карьер &lt;&amp;&gt;' in message
    assert '<code>55.123456, 37.654321</code>' in message
    assert 'pt=37.654321,55.123456&amp;z=16' in message
    assert 'Дата поездки: 2026-11-07' in message


def test_long_route_preserves_order_and_whole_cards():
    messages = route_messages(route(100))
    assert len(messages) > 1
    assert all(len(m.encode('utf-16-le')) // 2 <= 4000 for m in messages)
    combined = '\n'.join(messages)
    for i in range(100):
        assert combined.count(f'<b>{i + 1}. {i} Карьер') == 1
    assert combined.index('<b>1.') < combined.index('<b>100.')
    assert all(m.count('<code>') == m.count('Открыть на карте') for m in messages)


def test_extreme_labels_empty_and_unavailable_places():
    data = route(2, '&' * 10000)
    data['name'] = '&' * 10000
    for item in data['items']:
        item['place']['full_address'] = '&' * 10000
    assert all(len(m.encode('utf-16-le')) // 2 <= 4000 for m in route_messages(data))
    assert 'пока нет мест' in route_messages(route(0))[0]
    data['items'] = [{'status': 'skipped', 'place': None}]
    assert 'Место недоступно' in route_messages(data)[0]


def test_transport_and_partial_failure(monkeypatch):
    calls = []
    fail = False
    def handler(request):
        assert request.url.path.endswith('/sendMessage')
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'ok': not (fail and len(calls) == 2)})
    original = httpx.Client
    monkeypatch.setattr('urbex.infrastructure.telegram.httpx.Client',
                        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    data = route(30)
    send_route('test', 123, data)
    assert [c['text'] for c in calls] == route_messages(data)
    assert all(c['chat_id'] == '123' and c['parse_mode'] == 'HTML'
               and c['link_preview_options']['is_disabled'] for c in calls)
    calls.clear()
    fail = True
    with pytest.raises(DomainError, match='частично'):
        send_route('test', 123, data)
    assert len(calls) == 2


@pytest.mark.parametrize('error_type,expected', [
    (httpx.ConnectTimeout, 'не смог подключиться'),
    (httpx.ConnectError, 'не смог подключиться'),
    (httpx.ReadTimeout, 'Проверьте чат'),
])
def test_network_errors_are_specific_safe_and_not_retried(monkeypatch, caplog, error_type, expected):
    calls = []
    def handler(request):
        calls.append(request)
        raise error_type('secret-token-url', request=request)
    original = httpx.Client
    monkeypatch.setattr('urbex.infrastructure.telegram.httpx.Client',
                        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(DomainError, match=expected) as exc:
        send_route('test', 123, route())
    assert len(calls) == 1
    assert 'secret-token-url' not in str(exc.value) + caplog.text
    assert error_type.__name__ in caplog.text
