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
