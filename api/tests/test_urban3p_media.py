import httpx
import pytest
from domain.rules import DomainError
from infrastructure.osint import urban3p_media as media
from infrastructure.osint import osint_description as description


def test_com_gallery_uses_specialized_parser():
    url = 'https://urban3p.com/object17147/gallery'
    assert description._is_urban3p_url(url)
    assert description._urban3p_object_id(url) == '17147'
    assert description._extract_urban3p_image_urls(
        '<img src="https://img04.urban3p.ru/up/o/17147/gallery/384551_p.jpg">', '17147'
    ) == ['https://img04.urban3p.ru/up/o/17147/gallery/384551.jpg']


def test_relay_is_response_only_and_preserves_external_sources():
    url = 'https://img04.urban3p.ru/up/o/17147/gallery/384551_p.jpg'
    original = {'photos': [{'image_url': url, 'thumbnail_url': url, 'source_url': 'https://urban3p.com/object17147/gallery'}]}
    result = media.relay_report_images(original)
    assert result['photos'][0]['image_url'] == '/api/osint/urban3p/img04/17147/gallery/384551.jpg'
    assert original['photos'][0]['image_url'] == url
    assert result['photos'][0]['source_url'] == original['photos'][0]['source_url']


def test_relay_retries_and_caches_images(monkeypatch):
    media.fetch_image.cache_clear()

    calls = []
    def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            raise httpx.ConnectTimeout('temporary failure')
        return httpx.Response(200, content=b'\xff\xd8\xfftest')
    original = httpx.Client
    monkeypatch.setattr(media.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler)))
    for _ in range(2):
        assert media.fetch_image('img04', 17147, 'gallery', '384551.jpg') == b'\xff\xd8\xfftest'
    assert len(calls) == 2
    assert calls == [
        'https://img04.urban3p.ru/up/o/17147/gallery/384551.jpg',
        'https://img04.urban3p.com/up/o/17147/gallery/384551.jpg',
    ]
    with pytest.raises(DomainError):
        media.fetch_image('localhost', 17147, 'gallery', '384551.jpg')
    with pytest.raises(DomainError):
        media.fetch_image('img04', 17147, 'gallery', '../secret')
    media.fetch_image.cache_clear()


def test_browser_tls_fallback(monkeypatch):
    from curl_cffi import requests
    from types import SimpleNamespace
    media.fetch_image.cache_clear()
    original = httpx.Client
    def fail(request):
        raise httpx.ConnectError('TLS rejected')
    monkeypatch.setattr(media.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(fail)))
    monkeypatch.setattr(requests, 'get', lambda url, **kwargs: SimpleNamespace(status_code=200, content=b'\xff\xd8\xffphoto'))
    assert media.fetch_image('img04', 17147, 'gallery', '384557.jpg') == b'\xff\xd8\xffphoto'
    media.fetch_image.cache_clear()


def test_gallery_page_uses_com_mirror_when_ru_fails(monkeypatch):
    calls = []
    html = '<title>Бункер ЗРК</title>' + ' ' * 500
    def fetch(url):
        calls.append(url)
        return html if url == 'https://urban3p.com/object7957' else ''
    monkeypatch.setattr(description, '_fetch_urban3p_html_impersonated', fetch)
    assert description._fetch_urban3p_html('https://urban3p.ru/object7957') == html
    assert calls == ['https://urban3p.ru/object7957', 'https://urban3p.com/object7957']


def test_gallery_connection_failures_have_bounded_attempts(monkeypatch):
    from curl_cffi import requests
    calls = []
    def fail(url, **kwargs):
        calls.append(kwargs)
        raise OSError('TLS unavailable')
    monkeypatch.setattr(requests, 'get', fail)
    assert description._fetch_urban3p_html_impersonated('https://urban3p.ru/object7957') == ''
    assert len(calls) == 2
    assert all(call['timeout'] == 3 for call in calls)
