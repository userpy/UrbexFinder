import json
import httpx
import pytest
from domain.rules import DomainError
from infrastructure.integrations.telegram import prepare_route_share


def test_prepare_share_does_not_send_and_preserves_plain_text(monkeypatch):
    calls = []
    def handler(request):
        assert request.url.path.endswith('/savePreparedInlineMessage')
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'ok': True, 'result': {'id': 'prepared', 'expiration_date': 123}})
    original = httpx.Client
    monkeypatch.setattr('infrastructure.integrations.telegram.httpx.Client',
                        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    result = prepare_route_share('secret', 123, {'id': 42, 'name': 'Поездка <&>'}, 'https://site.example/routes/share?token=abc')
    assert result == {'id': 'prepared'}
    assert len(calls) == 1
    payload = calls[0]
    assert payload['user_id'] == 123
    assert payload['allow_user_chats'] and payload['allow_group_chats'] and payload['allow_channel_chats']
    assert payload['result']['input_message_content'] == {
        'message_text': 'Поездка <&>\nhttps://site.example/routes/share?token=abc',
    }


@pytest.mark.parametrize('response', [
    {'ok': False, 'description': 'secret-token'},
    {'ok': True, 'result': {}},
    {'ok': True, 'result': {'id': ''}},
])
def test_prepare_failure_is_safe(monkeypatch, response):
    original = httpx.Client
    monkeypatch.setattr('infrastructure.integrations.telegram.httpx.Client',
                        lambda **kwargs: original(transport=httpx.MockTransport(
                            lambda request: httpx.Response(200, json=response)), **kwargs))
    with pytest.raises(DomainError) as error:
        prepare_route_share('secret-token', 123, {'id': 42, 'name': 'Маршрут'}, 'https://site.example')
    assert error.value.status == 502
    assert 'secret-token' not in error.value.message
