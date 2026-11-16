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
