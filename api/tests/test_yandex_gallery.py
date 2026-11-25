import json
import pytest
from infrastructure.osint import service as osint
from infrastructure.osint import osint_description as description
from infrastructure.osint.osint_identity import source_key
from infrastructure.osint.yandex_gallery import org_gallery

URL = 'https://yandex.com/maps/org/aleksin_bor/110927843327/'
IMAGE = 'https://avatars.mds.yandex.net/get-altay/123/2a000001abc/%s'
PLACE = {'id': 189, 'name': 'Санаторий "Алексин Бор"',
         'region': 'Тульская область', 'latitude': 54.55188, 'longitude': 37.137548}

TESLA_PLACE = {
    'id': 7, 'name': 'Катушки Тесла',
    'latitude': 55.924186, 'longitude': 36.819986,
    'full_address': 'Почтовая улица, Истра, муниципальный округ Истра, Московская область',
}
TESLA_URL = 'https://yandex.com/maps/org/tesla_towers/65066224914/'


@pytest.fixture
def tesla_photos(monkeypatch):
    # Organization metadata observed on Maps; its pin is ~99 m from the card.
    data = {'stack': [{'results': {'items': [{
        'id': '65066224914', 'title': 'Башни Тесла',
        'address': 'Московская область, муниципальный округ Истра',
        'coordinates': [36.818533, 55.923832],
        'categories': [{'name': 'Достопримечательность'}],
        'photos': {'items': [{'urlTemplate': IMAGE}]},
    }]}}]}
    page = '<script class="state-view">' + json.dumps(data) + '</script>'
    monkeypatch.setattr(description, '_fetch_ymaps_html', lambda url: page)
    return description.yandex_maps_photos_for_links([{'url': TESLA_URL}])


def test_tesla_towers_gallery_matches_coils_and_recovers_cached_rejections(monkeypatch, tesla_photos):
    from infrastructure.osint import source_photos

    stored = {
        'photos': [], 'items': [], 'photos_total': 0, 'total': 0,
        'verification': {'version': 21, 'sources': [], 'photos': [{
            'candidate': photo, 'status': 'unconfirmed',
            'reasons': ['Недостаточно данных для привязки к конкретному объекту'],
        } for photo in tesla_photos]},
    }
    monkeypatch.setattr(osint, 'load_osint_report', lambda *a: stored)
    saved = []
    monkeypatch.setattr(osint, 'save_osint_report', lambda engine, id, report: saved.append(report) or report)
    monkeypatch.setattr(osint, 'yandex_maps_photos_for_links',
                        lambda *a: pytest.fail('Cached gallery should not need a new fetch'))
    monkeypatch.setattr(source_photos, 'discover_photos', lambda *a: [])

    fresh = osint._refilter_report({'photos': tesla_photos}, TESLA_PLACE)
    assert fresh['photos'] == tesla_photos
    result = osint.get_or_build_osint_report(None, '', '', TESLA_PLACE)
    assert result['photos'] == tesla_photos
    assert result['photos_total'] == 1
    assert saved and saved[0]['photos'] == tesla_photos
    assert source_photos.source_photos(TESLA_PLACE, stored) == tesla_photos


@pytest.mark.parametrize('changes', [
    {'latitude': None},
    {'latitude': 55.926},  # Nearby, but outside the existing 100 m identity threshold.
    {'latitude': 56.0},
    {'full_address': 'Тверская область'},
    {'name': 'Музей Николы Тесла'},
])
def test_tesla_alias_does_not_override_missing_coordinates_or_conflicts(tesla_photos, changes):
    report = osint._refilter_report({'photos': tesla_photos}, dict(TESLA_PLACE, **changes))
    assert report['photos'] == []


def test_tesla_alias_requires_coordinates_from_its_own_source(tesla_photos):
    photo = tesla_photos[0]
    photo['page_identity']['source_key'] = 'yandex_maps:999'
    assert osint._refilter_report({'photos': [photo]}, TESLA_PLACE)['photos'] == []


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
    from infrastructure.osint import source_photos
    monkeypatch.setattr(source_photos, 'discover_photos', lambda *a: [])
    monkeypatch.setattr(description, '_fetch_ymaps_html', lambda url: html())
    photos = description.yandex_maps_photos_for_links([{'url': URL}])
    assert source_photos.source_photos(PLACE, {'photos': photos}) == photos
    wrong_place = dict(PLACE, name='Санаторий Алексин Бор', latitude=56.0)
    assert source_photos.source_photos(wrong_place, {'photos': photos}) == []


def test_place_search_uses_matching_yandex_result_title_when_page_title_is_generic(monkeypatch):
    place = {
        'id': 3302,
        'name': 'Усадьба «Гребнево»',
        'full_address': 'Щёлковский городской округ, Московская область',
        'latitude': 55.9489,
        'longitude': 38.0868,
    }
    oid = '141562594761'
    search_html = (
        '<meta property="og:title" content="Яндекс Карты">'
        '<div data-id="141562594761">'
        '<div class="search-business-snippet-view__title">Усадьба Гребнево</div>'
        '<a href="/maps/org/grebnevo_estate/141562594761/"></a></div>'
    )
    gallery = {
        'stack': [{'results': {'items': [{
            'id': oid,
            'title': 'Усадьба Гребнево',
            'address': 'Щёлковский городской округ, Московская область',
            'coordinates': [38.087618, 55.949299],
            'categories': [{'name': 'Усадьба'}],
            'photos': {'items': [{'urlTemplate': IMAGE}]},
        }]}}]
    }
    gallery_html = '<script type="application/json" class="state-view">' + json.dumps(gallery) + '</script>'
    monkeypatch.setattr(
        description, '_fetch_ymaps_html',
        lambda url: search_html if '/maps/?' in url else gallery_html,
    )

    photos = description.yandex_maps_photos_for_place(place)
    assert len(photos) == 1
    assert photos[0]['engine'] == 'yandex_maps'
    assert photos[0]['page_identity']['latitude'] == 55.949299
