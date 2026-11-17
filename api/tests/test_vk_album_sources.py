from urbex.infrastructure import osint, osint_description as description
from urbex.infrastructure.osint_assess import assess_osint_items


def test_album_fetch_does_not_expand_to_group_or_wall(monkeypatch):
    url = 'https://vk.com/album-97053640_284116955'
    calls = []
    monkeypatch.setattr(description, '_fetch_vk_html', lambda _: '')
    def call(token, method, **params):
        calls.append(method)
        assert params == {'owner_id': -97053640, 'album_ids': '284116955'} or params == {'owner_id': -97053640, 'album_ids': 284116955}
        return {'items': [{'id': 284116955, 'title': 'Объект', 'description': 'Корпус снесён.'}]}
    monkeypatch.setattr(description, '_vk_call', call)
    items = description.vk_sources_for_links('token', [{'url': url}])
    assert calls == ['photos.getAlbums']
    assert items[0]['url'] == url
    assert assess_osint_items(items)['condition']['level'] == 'demolished'
    assert description.vk_sources_for_links('', [{'url': url}]) == []


def test_cached_report_drops_group_and_image_preserves_album():
    album = 'https://vk.com/album-97053640_284116955'
    image = 'https://lh3.googleusercontent.com/umsh/example'
    group = {'url': 'https://vk.com/club97053640', 'title': 'Заброшенные места',
             'snippet': 'Заброшенные места Московской области', 'engine': 'vk'}
    assert assess_osint_items([group])['condition']['level'] == 'unknown'
    place = {'name': 'Объект', 'description': f'{image}\n{album}'}
    report = osint._refilter_report({'items': [group], 'photos': [], 'assessment': {}}, place)
    assert [item['url'] for item in report['items']] == [album]
    assert report['assessment']['condition']['level'] == 'unknown'


def test_public_album_html_photos_and_text_are_scoped(monkeypatch):
    url = 'https://vk.com/album-97053640_284116955'
    html = '''<meta name="og:url" value="https://vk.ru/album-97053640_284116955">
    <meta name="og:description" value="Заброшенные места — группа">
    <div class="photos_album_intro"><h1>Сельская школа 07.05.22</h1>
    <div class="photos_album_intro_desc">Корпус <b>снесён</b>.<br>Фотоотчёт.</div></div>
    <div id="photos_container_photos">
      <div class="photos_row" data-id="-97053640_123"
        style="background-image: url(https://sun9-51.vkuserphoto.ru/a.jpg?quality=95&amp;cs=240x0)"></div>
      <div class="photos_row" data-id="-97053640_124"
        style="background-image: url(https://sun9-51.userapi.com/b.jpg)"></div>
      <div class="photos_row" data-id="-123_125"
        style="background-image: url(https://sun9-51.userapi.com/foreign.jpg)"></div>
      <div class="photos_row" data-id="-97053640_126"
        style="background-image: url(https://userapi.com.evil.example/a.jpg)"></div>
    </div><div class="photos_row" data-id="-97053640_127"
      style="background-image: url(https://sun9-51.userapi.com/sidebar.jpg)"></div>'''
    monkeypatch.setattr(description, '_fetch_vk_html', lambda _: html)
    monkeypatch.setattr(description, '_vk_call', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('HTML needs no API')))
    sources = description.vk_sources_for_links('', [{'url': url}])
    assert sources[0]['title'] == 'Сельская школа 07.05.22'
    assert sources[0]['snippet'] == 'Корпус снесён.\nФотоотчёт.'
    photos = description.vk_photos_for_links('', [{'url': url}])
    assert len(photos) == 2
    assert '&cs=240x0' in photos[0]['image_url']
    place = {'name': 'Холминская школа', 'region': 'Московская область', 'description': url}
    report = osint._refilter_report({'items': sources, 'photos': photos, 'assessment': {}}, place)
    assert report['photos'] == photos
    assert report['items'][0]['title'] == 'Сельская школа 07.05.22'
    assert report['assessment']['condition']['level'] == 'demolished'
    from urbex.infrastructure.vk_album import parse_vk_album
    assert parse_vk_album(html, 'https://vk.com/album-97053640_999')['photos'] == []
    assert parse_vk_album('<title>Войдите в VK</title>', url)['title'] == ''


def test_description_group_is_exact_match_despite_identity_conflicts():
    from urbex.infrastructure.osint_identity import verify_source
    place = {'name': 'Завод', 'full_address': 'Московская область'}
    group = {'url': 'https://vk.com/club42', 'title': 'Школа, Тверская область', 'engine': 'vk'}
    assert verify_source(place, group, ['https://m.vk.ru/public42']).status == 'accepted'
    assert verify_source(place, group, ['https://vk.com/club43']).status == 'rejected'
    place['description'] = 'https://m.vk.ru/public42'
    assert osint._filter_sources([group], place) == [group]
    report = osint._refilter_report({'items': [group]}, place)
    assert any(item['url'] == group['url'] for item in report['items'])
    assert report['verification']['sources'][0]['evidence'] == ['reference']


def test_named_description_group_survives_fresh_report_without_vk_access(monkeypatch):
    monkeypatch.setattr(osint, 'description_photos_for_links', lambda *a, **k: [])
    monkeypatch.setattr(osint, 'vk_sources_for_links', lambda *a, **k: [])
    url = 'https://vk.com/old_factory'
    place = {'id': 1, 'name': 'Завод', 'description': url}
    fresh = osint.build_osint_report('', '', place)
    assert [item['url'] for item in fresh['items']] == [url]
    cached = osint._refilter_report({'items': []}, place)
    assert [item['url'] for item in cached['items']] == [url]


def test_group_reference_does_not_automatically_confirm_wall_posts():
    from urbex.infrastructure.osint_identity import verify_source
    post = {'url': 'https://vk.com/wall-42_123', 'title': 'Школа'}
    assert verify_source({'name': 'Завод'}, post, ['https://vk.com/club42']).status == 'rejected'


def test_group_api_photos_keep_verified_group_provenance(monkeypatch):
    url = 'https://vk.com/old_factory'
    monkeypatch.setattr(description, '_fetch_vk_html', lambda _: '')
    monkeypatch.setattr(description, '_resolve_screen_name', lambda *a: -42)
    monkeypatch.setattr(description, '_photos_get', lambda *a: [
        {'owner_id': owner, 'id': 7, 'sizes': [{'url': f'https://sun9.userapi.com/{owner}.jpg',
                                            'width': 1280, 'height': 720}]}
        for owner in [-42, -99]
    ])
    photos = description.vk_photos_for_links('token', [{'url': url}])
    assert len(photos) == 1
    assert photos[0]['source_url'] == url
    assert photos[0]['photo_page_url'] == 'https://vk.com/photo-42_7'
    place = {'name': 'Завод', 'description': url}
    assert osint._refilter_report({'photos': photos}, place)['photos'] == photos
    assert osint._refilter_report({'photos': photos}, dict(place, description=''))['photos'] == []


def test_group_html_photos_survive_verification_without_token(monkeypatch):
    url = 'https://vk.com/club42'
    monkeypatch.setattr(description, '_fetch_vk_html', lambda _: '<img src="https://sun9.userapi.com/impg/factory.jpg">')
    photos = description.vk_photos_for_links('', [{'url': url}])
    assert len(photos) == 1
    assert osint._refilter_report({'photos': photos}, {'name': 'Завод', 'description': url})['photos'] == photos


def test_cached_report_retries_missing_vk_group_photos(monkeypatch):
    url = 'https://vk.com/club42'
    photo = {'engine': 'vk', 'source_url': url, 'query': url,
             'image_url': 'https://sun9.userapi.com/factory.jpg'}
    stored = {'items': [], 'photos': []}
    monkeypatch.setattr(osint, 'load_osint_report', lambda *a: stored)
    monkeypatch.setattr(osint, 'save_osint_report', lambda engine, id, report: report)
    calls = []
    def fetch(token, links, limit):
        calls.append((token, links[0]['url']))
        return [photo]
    monkeypatch.setattr(osint, 'vk_photos_for_links', fetch)
    place = {'id': 42, 'name': 'Завод', 'description': url}
    result = osint.get_or_build_osint_report(None, '', '', place, vk_token='token')
    assert result['photos'] == [photo]
    assert calls == [('token', url)]
    stored.update(photos=[], vk_photos_checked_at=result['vk_photos_checked_at'])
    osint.get_or_build_osint_report(None, '', '', place, vk_token='token')
    assert len(calls) == 1


def test_group_html_supports_vk_cdn_and_rejects_lookalike_hosts():
    html = '''<img data-src="https://sun9.vkuserphoto.ru/factory.jpg?quality=95&amp;x=1">
    <img src="https://userapi.com.evil.example/factory.jpg">
    <img src="https://sun9.userapi.com/emoji/smile.png">'''
    assert description._extract_vk_image_urls(html) == ['https://sun9.vkuserphoto.ru/factory.jpg?quality=95&x=1']
