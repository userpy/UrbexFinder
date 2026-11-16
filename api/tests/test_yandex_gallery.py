import json
from urbex.infrastructure import osint, osint_description as description
from urbex.infrastructure.osint_identity import source_key
from urbex.infrastructure.yandex_gallery import org_gallery

URL = 'https://yandex.com/maps/org/aleksin_bor/110927843327/'
IMAGE = 'https://avatars.mds.yandex.net/get-altay/123/2a000001abc/%s'
PLACE = {'id': 189, 'name': 'Санаторий "Алексин Бор"',
         'region': 'Тульская область', 'latitude': 54.55188, 'longitude': 37.137548}


def html(oid='110927843327'):
    data = {'stack': [{'results': {'items': [
        {'id': '999', 'photos': {'items': [{'urlTemplate': IMAGE.replace('123/', '999/')}] }},
        {'id': oid, 'title': 'Алексин бор', 'address': 'Тульская область',
         'categories': [{'name': 'Санаторий'}], 'coordinates': [37.137831, 54.552032],
         'photos': {'items': [{'urlTemplate': IMAGE}]},
         'relatedAdverts': [{'urlTemplate': IMAGE.replace('123/', '888/')}]}]}}]}
    return '<script type="application/json" class="state-view">' + json.dumps(data) + '</script>'


def test_yandex_identity_uses_org_id_not_domain_slug_or_view_query():
    assert source_key(URL) == source_key('https://yandex.ru/maps/org/other_slug/110927843327/gallery/?ll=1,2')
    assert source_key(URL) != source_key(URL.replace('110927843327', '1109278433270'))
    assert source_key(URL) != source_key(URL.replace('yandex.com', 'yandex.com.evil.test'))


def test_gallery_reads_only_matching_org_not_adverts_or_other_results():
    parsed = org_gallery(html(), '110927843327', URL)
    assert parsed['templates'] == [IMAGE]
    assert parsed['identity']['latitude'] == 54.552032
    assert org_gallery(html('777'), '110927843327', URL) == {}


def test_fresh_gallery_passes_identity_and_search_cannot_supply_images(monkeypatch):
    monkeypatch.setattr(description, '_fetch_ymaps_html', lambda url: html())
    photos = description.yandex_maps_photos_for_links([{'url': URL}])
    assert len(photos) == 1
    assert photos[0]['gallery_source_key'] == source_key(URL)
    # Discovery queries may differ; organization provenance remains explicit.
    photos[0]['query'] = 'https://yandex.com/maps/?text=Алексин'
    result = osint._refilter_report({'photos': photos}, PLACE)
    assert result['photos'] == photos
    assert len(result['items']) == 1
    assert result['items'][0]['page_identity']['latitude'] == 54.552032


def test_missing_cached_yandex_gallery_recovers_with_cooldown(monkeypatch):
    monkeypatch.setattr(description, '_fetch_ymaps_html', lambda url: html())
    photo = description.yandex_maps_photos_for_links([{'url': URL}])[0]
    stored = {'items': [{'url': URL, 'title': 'Алексин бор, санаторий, Тульская область'}],
              'photos': [], 'total': 1, 'photos_total': 0}
    monkeypatch.setattr(osint, 'load_osint_report', lambda *args: stored.copy())
    monkeypatch.setattr(osint, 'save_osint_report', lambda engine, id, r: (stored.update(r) or r))
    calls = []
    monkeypatch.setattr(osint, 'yandex_maps_photos_for_links', lambda *a: calls.append(1) or [])
    osint.get_or_build_osint_report(None, '', '', PLACE)
    osint.get_or_build_osint_report(None, '', '', PLACE)
    assert calls == [1]
    stored['yandex_photos_checked_at'] = 0
    monkeypatch.setattr(osint, 'yandex_maps_photos_for_links', lambda *a: [photo])
    assert osint.get_or_build_osint_report(None, '', '', PLACE)['photos'] == [photo]


def test_confirmed_maps_gallery_is_available_on_place_card(monkeypatch):
    from urbex.infrastructure import source_photos
    monkeypatch.setattr(description, '_fetch_ymaps_html', lambda url: html())
    photos = description.yandex_maps_photos_for_links([{'url': URL}])
    assert source_photos.source_photos(PLACE, {'photos': photos}) == photos
    wrong_place = dict(PLACE, name='Санаторий Алексин Бор', latitude=56.0)
    assert source_photos.source_photos(wrong_place, {'photos': photos}) == []
