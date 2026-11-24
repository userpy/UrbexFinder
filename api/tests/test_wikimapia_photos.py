import pytest

from urbex.infrastructure import osint, osint_description as description
from urbex.infrastructure.wikimapia import gallery_urls, photo_url


def test_gallery_uses_only_photo_host_and_best_available_size():
    html = '''<img src="/img/logo.jpg">
      <a href="//photos.wikimapia.org/p/00/08/50/63/08_1280.jpg">
      <img src="http://photos.wikimapia.org/p/00/08/50/63/08_60.jpg"></a>
      <img src="https://photos.wikimapia.org.evil.test/p/00/08/50/63/09.jpg">
      <img src="https://photos.wikimapia.org/p/00/08/50/63/09_1280.jpg">'''
    assert gallery_urls(html, 'https://wikimapia.org/123/ru/test') == [
        'https://photos.wikimapia.org/p/00/08/50/63/08_1280.jpg',
        'https://photos.wikimapia.org/p/00/08/50/63/09_1280.jpg',
    ]
    assert photo_url('https://photos.wikimapia.org/p/logo.jpg') is None


def test_gallery_source_opens_selected_object_on_map_without_changing_provenance():
    from copy import deepcopy
    from urllib.parse import parse_qs, urlparse
    from urbex.infrastructure.wikimapia import gallery_source_links
    from urbex.infrastructure.osint_identity import source_key
    source = 'https://wikimapia.org/1912109/ru/'
    photo = {'source_url': source, 'image_url': 'https://photos.wikimapia.org/p/00/00/75/53/57_big.jpg',
             'query': source, 'page_identity': {
                 'source_key': source_key(source), 'title': 'РТЦ (С-25) «Сочельник»',
                 'latitude': 56.14487995, 'longitude': 37.4071168,
             }}
    place = {'latitude': 56.145, 'longitude': 37.4074, 'description': 'Описание'}
    before = deepcopy((photo, place))
    result = gallery_source_links([photo], place)[0]
    link = urlparse(result['source_url'])
    assert link.scheme == 'https' and link.netloc == 'wikimapia.org' and link.path == '/'
    assert parse_qs(link.fragment) == {
        'lang': ['en'], 'lat': ['56.145000'], 'lon': ['37.407400'], 'z': ['13'],
        'm': ['w'], 'show': ['/1912109/ru/РТЦ-(С-25)-«Сочельник»'],
    }
    assert source_key(result['source_url']) == source_key(source)
    assert result['original_source_url'] == result['query'] == source
    assert result['image_url'] == photo['image_url']
    assert (photo, place) == before
    assert gallery_source_links([result], place) == [result]


def test_gallery_map_link_uses_only_same_object_metadata():
    from urbex.infrastructure.wikimapia import gallery_source_links
    photo = {'source_url': 'https://wikimapia.org/123/ru/', 'page_identity': {
        'source_key': 'wikimapia.org:999', 'latitude': 56, 'longitude': 37, 'title': 'Wrong place',
    }}
    assert gallery_source_links([photo], {}) == [photo]
    photo['page_identity']['source_key'] = 'wikimapia.org:123'
    result = gallery_source_links([photo], {})[0]
    assert 'lat=56.000000&lon=37.000000' in result['source_url']
    other = {'source_url': 'https://urban3p.ru/object123'}
    assert gallery_source_links([other], {'latitude': 56, 'longitude': 37}) == [other]


def test_wikimapia_map_share_url_resolves_to_object_link():
    from urbex.infrastructure.osint_description import links_from_description
    from urbex.infrastructure.osint_identity import source_key
    from urbex.infrastructure.osint_identity import verify_report
    shared = (
        'https://wikimapia.org/#lang=en&lat=55.738250&lon=37.968342&z=16&m=w'
        '&show=/13353625/ru&search=%D0%9E%D0%BB%D1%8C%D0%B3%D0%B8%D0%BD%D0%BE'
    )
    links = links_from_description(f'Источник: {shared}')
    assert links[0]['url'] == 'https://wikimapia.org/13353625/ru'
    assert links[0]['category'] == 'wikimapia'
    assert source_key(shared) == source_key(links[0]['url']) == 'wikimapia.org:13353625'
    place = {
        'name': 'Небольшой заброшенный завод',
        'description': f'Заброшенный завод. {shared}',
        'latitude': 55.7357,
        'longitude': 37.9776,
        'full_address': 'Дальняя улица, Керамик, Балашиха, Московская область',
    }
    report = verify_report({'items': links, 'photos': []}, place, [links[0]['url']])
    assert [row['url'] for row in report['items']] == [links[0]['url']]


@pytest.mark.parametrize('shown, expected', [
    ('/1802949/Former-Starting-Positions-S-25-SA-1-Guild-/photo/1087688', '/1802949'),
    ('/1802949/en/Former-Starting-Positions-S-25-SA-1-Guild/photo/1087688', '/1802949/en'),
    ('/1802949/ru/Бывшие-стартовые-позиции/photo/1087688', '/1802949/ru'),
    ('/1802949/photo/1087688', '/1802949'),
    ('/1802949/ru/', '/1802949/ru'),
])
def test_map_photo_share_resolves_to_same_object(shown, expected):
    from urbex.infrastructure.osint_identity import source_key
    from urbex.infrastructure.wikimapia import object_url
    shared = 'https://wikimapia.org/#lang=en&lat=56.144976&lon=37.407417&show=' + shown
    url = 'https://wikimapia.org' + expected
    assert object_url(shared) == url
    assert source_key(shared) == source_key(url) == 'wikimapia.org:1802949'
    assert description.links_from_description(shared)[0]['url'] == url
    assert description.links_from_description(shared)[0]['category'] == 'wikimapia'


@pytest.mark.parametrize('url', [
    'https://wikimapia.org.evil.test/#show=/1802949/photo/1087688',
    'https://user:password@wikimapia.org/#show=/1802949/photo/1087688',
    'https://wikimapia.org:1234/#show=/1802949/photo/1087688',
    'https://wikimapia.org/#show=//evil.test/1802949',
    'https://wikimapia.org/#show=/1802949/photo/not-a-photo-id',
])
def test_invalid_map_photo_shares_are_not_object_links(url):
    from urbex.infrastructure.wikimapia import object_url
    assert object_url(url) is None


def test_fetch_map_photo_share_requests_object_page(monkeypatch):
    import httpx
    from urbex.infrastructure.wikimapia import fetch_html
    shared = ('https://wikimapia.org/#lang=en&lat=56.144976&lon=37.407417'
              '&show=/1802949/Former-Starting-Positions-S-25-SA-1-Guild-/photo/1087688')
    html = '<title>Former Starting Positions</title>' + ' ' * 500
    requests = []
    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(200, text=html)
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(
        transport=httpx.MockTransport(respond),
        **{key: value for key, value in kwargs.items() if key != 'transport'},
    ))
    assert fetch_html(shared) == html
    assert requests == ['https://wikimapia.org/1802949']


def test_map_viewport_does_not_override_distant_object_coordinates():
    from urbex.infrastructure.osint_identity import source_key, verify_report
    shared = ('https://wikimapia.org/#lat=56.145&lon=37.4074'
              '&show=/1802949/Former-Starting-Positions-S-25-SA-1-Guild-/photo/1087688')
    place = {'name': 'Полузаброшенный узел связи у РТЦ С-25',
             'description': shared, 'latitude': 56.145, 'longitude': 37.4074}
    link = description.links_from_description(shared)[0]
    identity = {'source_key': source_key(link['url']),
                'title': 'Former Starting Positions S-25 "SA-1 Guild"',
                'latitude': 56.165555, 'longitude': 37.3962831}
    photo = {'engine': 'wikimapia', 'source_url': link['url'], 'query': shared,
             'page_identity': identity,
             'image_url': 'https://photos.wikimapia.org/p/00/01/08/76/88_big.jpg'}
    result = verify_report({'items': [dict(link, page_identity=identity)],
                            'photos': [photo]}, place, [shared])
    assert result['items'] == []
    assert result['photos'] == []


def test_object_gallery_has_wikimapia_source(monkeypatch):
    page = 'https://wikimapia.org/123/ru/test'
    monkeypatch.setattr(description, '_fetch_generic_html', lambda _: '''
        <title>Полигон Астрофизика</title>
        <img src="//photos.wikimapia.org/p/00/08/50/63/08_1280.jpg">''')
    photos = description.generic_page_photos_for_links([{'url': page}])
    assert len(photos) == 1
    assert photos[0]['engine'] == 'wikimapia'
    assert photos[0]['source_url'] == page
    assert photos[0]['title'] == 'Полигон Астрофизика'


def test_astrofizika_cached_report_recovers_direct_photos_and_rejects_headquarters():
    url = 'http://photos.wikimapia.org/p/00/08/50/63/08_1280.jpg'
    place = {'name': 'Бывший исследовательский комплекс-полигон НПО "Астрофизика"',
             'region': 'Московская область', 'description': url}
    wrong = {'title': 'Национальный центр лазерных систем и комплексов Астрофизика',
             'source_url': 'https://example.org/headquarters',
             'image_url': 'https://example.org/photo.jpg', 'engine': 'web'}
    correct = dict(wrong, title='Бывший полигон НПО Астрофизика в Грибаново')
    assert osint._filter_photos([wrong, correct], place) == [correct]
    report = osint._refilter_report({'photos': [wrong]}, place)
    assert report['photos_total'] == 1
    assert report['photos'][0]['image_url'] == url.replace('http:', 'https:')
    assert osint._refilter_report(report, place)['photos'] == report['photos']


def test_direct_photo_is_not_fetched_as_html(monkeypatch):
    monkeypatch.setattr(description, '_fetch_generic_html',
                        lambda _: (_ for _ in ()).throw(AssertionError('Image fetched as HTML')))
    assert description.generic_page_photos_for_links([
        {'url': 'https://photos.wikimapia.org/p/00/08/50/63/08_1280.jpg'}]) == []


def test_wikimapia_query_is_not_truncated():
    query = osint._queries_for({'name': 'Очень длинное название ' * 20})[0]
    assert 'site:wikimapia.org' in query
    assert query.endswith(')')


def test_wikimapia_gallery_has_independent_page_budget(monkeypatch):
    page = 'https://wikimapia.org/123/ru/test'
    fetched = []
    def fetch(url):
        fetched.append(url)
        return '<img src="https://photos.wikimapia.org/p/00/08/50/63/08_1280.jpg">'
    monkeypatch.setattr(description, '_fetch_generic_html', fetch)
    links = [{'url': f'https://example.org/{i}'} for i in range(10)] + [{'url': page}]
    photos = description.wikimapia_photos_for_links(links)
    assert fetched == [page]
    assert len(photos) == 1
    assert description.links_from_description(page)[0]['category'] == 'wikimapia'


def test_saved_wikimapia_gallery_retries_with_cooldown(monkeypatch):
    page = 'https://wikimapia.org/123/ru/test'
    place = {'id': 1, 'name': 'Полигон', 'description': page}
    stored = {'items': [], 'photos': []}
    monkeypatch.setattr(osint, 'load_osint_report', lambda *args: stored.copy())
    def save(engine, place_id, report):
        stored.update(report)
        return report
    monkeypatch.setattr(osint, 'save_osint_report', save)
    calls = []
    monkeypatch.setattr(osint, 'wikimapia_photos_for_links', lambda *args: calls.append(1) or [])
    osint.get_or_build_osint_report(None, '', '', place)
    osint.get_or_build_osint_report(None, '', '', place)
    assert calls == [1]
    stored['wikimapia_checked_at'] = 0
    photo = {'engine': 'wikimapia', 'source_url': page, 'title': 'Фото объекта',
             'image_url': 'https://photos.wikimapia.org/p/00/08/50/63/08_1280.jpg'}
    monkeypatch.setattr(osint, 'wikimapia_photos_for_links', lambda *args: [photo])
    assert osint.get_or_build_osint_report(None, '', '', place)['photos'] == [photo]


def test_session_refresh_loads_object_without_running_javascript(monkeypatch):
    import httpx
    from urbex.infrastructure.wikimapia import fetch_html
    calls = []
    html = '<title>РЛС Дунай</title>' + ' ' * 500
    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, text='<script>document.cookie="nsess=' + 'a' * 32 + '";</script>')
        assert request.headers['cookie'] == 'nsess=' + 'a' * 32
        return httpx.Response(200, text=html)
    original = httpx.Client
    original_transport = httpx.HTTPTransport
    retries = []
    monkeypatch.setattr(
        httpx, 'HTTPTransport',
        lambda **kwargs: retries.append(kwargs['retries']) or original_transport(**kwargs),
    )
    monkeypatch.setattr(
        httpx, 'Client',
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **{
            key: value for key, value in kwargs.items() if key != 'transport'
        }),
    )
    assert fetch_html('http://wikimapia.org/3787319/ru/') == html
    assert len(calls) == 2
    assert retries == [1]
    assert all(r.url.scheme == 'https' for r in calls)


def test_session_refresh_follows_canonical_redirect_to_same_object(monkeypatch):
    import httpx
    from urbex.infrastructure.wikimapia import fetch_html
    calls = []
    html = '<title>Административное здание (Балашиха)</title>' + ' ' * 500

    def respond(request):
        calls.append(request)
        assert 'Mozilla/5.0' in request.headers['user-agent']
        if len(calls) == 1:
            return httpx.Response(
                200,
                text='<script>document.cookie="nsess=' + 'b' * 32 + '";</script>',
            )
        if len(calls) == 2:
            assert request.headers['cookie'] == 'nsess=' + 'b' * 32
            return httpx.Response(
                301,
                headers={'location': '/13353625/ru/administrative-building'},
            )
        return httpx.Response(200, text=html)

    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        'Client',
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **{
            key: value for key, value in kwargs.items() if key != 'transport'
        }),
    )
    assert fetch_html('https://wikimapia.org/13353625/ru') == html
    assert len(calls) == 3


def test_session_refresh_handles_challenge_after_canonical_redirect(monkeypatch):
    import httpx
    from urbex.infrastructure.wikimapia import fetch_html
    calls = []
    html = '<title>Детская база отдыха Гагарина</title>' + ' ' * 500

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200,
                text='<script>document.cookie="nsess=' + 'a' * 32 + '";</script>',
            )
        if len(calls) == 2:
            assert request.headers['cookie'] == 'nsess=' + 'a' * 32
            return httpx.Response(301, headers={'location': '/17109228/ru/gagarina'})
        if len(calls) == 3:
            assert request.url.path == '/17109228/ru/gagarina'
            return httpx.Response(
                200,
                text='<script>document.cookie="nsess=' + 'b' * 32 + '";</script>',
            )
        assert request.headers['cookie'] == 'nsess=' + 'b' * 32
        return httpx.Response(200, text=html)

    original = httpx.Client
    monkeypatch.setattr(
        httpx, 'Client',
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **{
            key: value for key, value in kwargs.items() if key != 'transport'
        }),
    )
    assert fetch_html('https://wikimapia.org/17109228/ru') == html
    assert len(calls) == 4


def test_object_meta_coordinates_confirm_dunay_and_ignore_map_and_neighbours():
    from urbex.infrastructure.osint_identity import extract_page_identity, verify_source
    url = 'https://wikimapia.org/3787319/ru/'
    html = '''<h1>Территория бывшей РЛС ПРО Дунай-3М</h1>
    <meta property="og:url" content="http://wikimapia.org/3787319/ru/test">
    <meta property="place:location:latitude" content="55.4800267">
    <meta property="place:location:longitude" content="36.6482017">
    <script>map = {lat: 1, lon: 2}; nearby = {latitude: 3, longitude: 4}</script>'''
    identity = extract_page_identity(html, url)
    assert (identity['latitude'], identity['longitude']) == (55.4800267, 36.6482017)
    place = {'name': 'Бывший Дунай', 'description': 'Заброшенная РЛС Дунай-3М',
             'latitude': 55.4806, 'longitude': 36.6485}
    assert verify_source(place, {'url': url, 'page_identity': identity}).status == 'accepted'
    assert 'latitude' not in extract_page_identity(html, 'https://wikimapia.org/999/ru/')
    assert 'latitude' not in extract_page_identity(html, 'https://example.org/3787319')


def test_session_fetch_does_not_follow_redirect_to_other_hosts_or_objects(monkeypatch):
    import httpx
    from urbex.infrastructure.wikimapia import fetch_html
    original = httpx.Client
    for target in ['http://127.0.0.1/private', 'https://wikimapia.org/999', 'https://wikimapia.org.evil.test/3787319']:
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(302, headers={'location': target})
        monkeypatch.setattr(
            httpx, 'Client',
            lambda **kwargs: original(transport=httpx.MockTransport(respond), **{
                key: value for key, value in kwargs.items() if key != 'transport'
            }),
        )
        assert fetch_html('https://wikimapia.org/3787319') == ''
        assert len(calls) == 1


def test_cached_unconfirmed_wikimapia_recovers_identity_then_gallery(monkeypatch):
    url = 'https://wikimapia.org/3787319/ru/'
    place = {'id': 3477, 'name': 'Бывший Дунай', 'description': 'РЛС Дунай-3М',
             'latitude': 55.4806, 'longitude': 36.6485}
    candidate = {'url': url, 'title': 'РЛС Дунай-3М'}
    stored = {'items': [], 'photos': [], 'source_candidates': [candidate]}
    monkeypatch.setattr(osint, 'load_osint_report', lambda *a: stored)
    monkeypatch.setattr(osint, 'save_osint_report', lambda engine, id, report: report)
    identity = {'source_key': 'wikimapia.org:3787319', 'title': 'РЛС Дунай-3М',
                'latitude': 55.4800267, 'longitude': 36.6482017}
    monkeypatch.setattr(osint, 'enrich_candidates', lambda *a: [dict(candidate, page_identity=identity)])
    photo = {'engine': 'wikimapia', 'source_url': url, 'query': url,
             'page_identity': identity, 'image_url': 'https://photos.wikimapia.org/p/00/08/50/63/08_1280.jpg'}
    monkeypatch.setattr(osint, 'wikimapia_photos_for_links', lambda *a: [photo])
    report = osint.get_or_build_osint_report(None, '', '', place)
    assert report['photos'] == [photo]
    assert report['items'][0]['url'] == url
    assert report['wikimapia_identity_checked_at'] > 0


def test_cached_exact_title_wikimapia_is_rechecked_when_coordinates_are_missing(monkeypatch):
    url = 'https://wikimapia.org/14892051/ru/Заброшенный-детский-сад'
    place = {
        'id': 3137,
        'name': 'Заброшенный детский сад',
        'description': '',
        'full_address': '113, Трубино, городской округ Щёлково, Московская область',
        'latitude': 55.992,
        'longitude': 38.1273,
    }
    candidate = {'url': url, 'title': 'Заброшенный детский сад (Икша)'}
    stored = {'items': [candidate], 'photos': []}
    identity = {
        'source_key': 'wikimapia.org:14892051',
        'title': 'Заброшенный детский сад (Икша)',
        'latitude': 56.1870754,
        'longitude': 37.5090153,
    }
    enrich_calls = []
    gallery_calls = []
    monkeypatch.setattr(osint, 'load_osint_report', lambda *args: stored)
    monkeypatch.setattr(osint, 'save_osint_report', lambda engine, id, report: report)
    monkeypatch.setattr(
        osint, 'enrich_candidates',
        lambda place, rows, refs: enrich_calls.extend(rows) or [
            dict(candidate, page_identity=identity),
        ],
    )
    monkeypatch.setattr(
        osint, 'wikimapia_photos_for_links',
        lambda *args: gallery_calls.append(args) or [],
    )

    report = osint.get_or_build_osint_report(None, '', '', place)

    assert enrich_calls == [candidate]
    assert report['items'] == []
    assert not gallery_calls
    assert report['wikimapia_identity_checked_at'] > 0


def test_gallery_prefers_full_size_big_links_over_75_pixel_thumbnails():
    assert gallery_urls('''<a href="http://photos.wikimapia.org/p/00/00/55/48/42_big.jpg">
        <img src="http://photos.wikimapia.org/p/00/00/55/48/42_75.jpg"></a>''',
        'https://wikimapia.org/3787319') == ['https://photos.wikimapia.org/p/00/00/55/48/42_big.jpg']


def test_gallery_preserves_actual_thumbnail_for_each_original(monkeypatch):
    original = 'https://photos.wikimapia.org/p/00/00/75/53/57_big.jpg'
    thumbnail = original.replace('_big', '_75')
    monkeypatch.setattr(description, '_fetch_generic_html', lambda _: f'''
        <a href="{original}"><img src="{thumbnail}"></a>
        <img src="https://photos.wikimapia.org/p/00/00/75/53/60_75.jpg">''')
    photos = description.wikimapia_photos_for_links([{'url': 'https://wikimapia.org/123/ru/'}])
    assert photos[0]['image_url'] == original
    assert photos[0]['thumbnail_url'] == thumbnail
    assert photos[1]['image_url'] == photos[1]['thumbnail_url']


def test_broken_translation_recovers_same_objects_english_metadata(monkeypatch):
    from urbex.infrastructure import wikimapia
    broken = '<title></title>Информация недоступна (ошибка RK n.22)'
    english = '<h1>Former camp</h1><meta property="place:location:latitude" content="55.6">'
    calls = []
    monkeypatch.setattr(wikimapia, '_fetch_html',
                        lambda url: calls.append(url) or (english if '/en/' in url else broken))
    assert wikimapia.fetch_html('https://wikimapia.org/123/ru/camp') == english
    assert calls == ['https://wikimapia.org/123/ru/camp', 'https://wikimapia.org/123/en/']


def test_translation_failure_preserves_original_gallery_and_does_not_loop(monkeypatch):
    from urbex.infrastructure import wikimapia
    broken = 'Информация недоступна (ошибка RK n.22)'
    calls = []
    monkeypatch.setattr(wikimapia, '_fetch_html', lambda url: calls.append(url) or broken)
    assert wikimapia.fetch_html('https://wikimapia.org/123/en/') == broken
    assert calls == ['https://wikimapia.org/123/en/']


def test_wikimapia_gallery_does_not_truncate_at_generic_six_photo_limit(monkeypatch):
    images = [f'https://photos.wikimapia.org/p/00/01/08/76/{n:02}_big.jpg' for n in range(7)]
    monkeypatch.setattr(description, '_fetch_generic_html',
                        lambda _: ''.join(f'<img src="{url}">' for url in images))
    photos = description.wikimapia_photos_for_links([{'url': 'https://wikimapia.org/123/ru/'}])
    assert [photo['image_url'] for photo in photos] == images
