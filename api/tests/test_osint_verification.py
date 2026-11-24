import json
import pytest
from urbex.infrastructure.osint_identity import (
    VERSION,
    extract_page_identity,
    source_key,
    verify_report,
    verify_source,
)
from urbex.infrastructure import osint, osint_evidence

SOURCE = 'http://wikimapia.org/38437817/ru/Убежище'
PLACE = {'id': 1, 'name': 'Убежище гражданской обороны (ru)',
         'full_address': 'улица Юлиана Семёнова, дом 6, Москва',
         'latitude': 55.64085, 'longitude': 37.39277, 'description': SOURCE}


def item(title='Убежище', url='https://example.org/object', **extra):
    return dict(title=title, url=url, snippet='', **extra)


def primary(row, **extra):
    return dict(row, page_identity=dict(source_key=source_key(row['url']), **extra))


def test_reference_identity_is_not_url_prefix_or_engine_label():
    assert verify_source(PLACE, item(url='https://wikimapia.org/38437817/en/Shelter'), [SOURCE]).status == 'accepted'
    assert verify_source(PLACE, item(url='https://wikimapia.org/384378170/en/Shelter'), [SOURCE]).status == 'unconfirmed'
    assert verify_source(PLACE, item(engine='description'), [SOURCE]).status == 'unconfirmed'
    assert source_key('https://example.org/x?a=1') != source_key('https://example.org/x?a=2')
    assert source_key('https://wikimapia.org.evil.example/38437817') != source_key(SOURCE)


def test_generic_type_and_city_are_not_identity():
    assert verify_source(PLACE, item('Убежище гражданской обороны — Москва')).status == 'unconfirmed'
    assert verify_source(PLACE, item('Убежище', query='Юлиана Семенова 6')).status == 'unconfirmed'


@pytest.mark.parametrize('address', ['улица Юлиана Семенова, дом 16, Москва', 'улица Дубровская, дом 6, Москва'])
def test_wrong_address_overrides_reference(address):
    candidate = primary(item(url=SOURCE), address=address)
    assert verify_source(PLACE, candidate, [SOURCE]).status == 'rejected'


def test_full_address_normalization_and_missing_house():
    candidate = primary(item(), address='ул. Юлиана Семенова, 6, Москва')
    assert verify_source(PLACE, candidate).status == 'accepted'
    candidate['page_identity']['address'] = 'улица Юлиана Семенова, Москва'
    assert verify_source(PLACE, candidate).status == 'unconfirmed'


def test_coordinates_require_name_type_and_precision():
    place = dict(PLACE, name='Убежище завода АЗЛК')
    row = primary(item('Убежище завода АЗЛК'), latitude=55.64086, longitude=37.39278)
    assert verify_source(place, row).status == 'accepted'
    row['page_identity']['latitude'] = 56.0
    assert verify_source(place, row).status == 'rejected'
    assert verify_source(place, primary(item('Больница АЗЛК'), latitude=55.64085, longitude=37.39277)).status == 'rejected'


def test_pushkino_church_yandex_address_and_wikimapia_name_variants_confirm_photos():
    place = {
        'name': 'Церковь Спаса Нерукотворного образа. Пушкино (Клязьма)',
        'full_address': '20, Лермонтовская улица, микрорайон Клязьма, Пушкино, '
                        'Пушкинский городской округ, Московская область, 141200, Россия',
        'latitude': 55.977016,
        'longitude': 37.837824,
    }
    yandex_url = 'https://yandex.com/maps/org/church/1044286577/'
    wikimapia_url = 'http://wikimapia.org/8778577/ru/Храм-Спаса-Нерукотворного-Образа-в-Клязьме'
    yandex = item(
        'Церковь Спаса Нерукотворного Образа, Православный храм',
        url=yandex_url,
        engine='yandex_maps',
        page_identity={
            'source_key': source_key(yandex_url),
            'title': 'Церковь Спаса Нерукотворного Образа, Православный храм',
            'address': 'Пушкино, микрорайон Клязьма, Лермонтовская ул., 20',
            'latitude': 55.976953,
            'longitude': 37.837691,
        },
    )
    wikimapia = item(
        'Храм Спаса Нерукотворного Образа в Клязьме - Пушкино',
        url=wikimapia_url,
        page_identity={
            'source_key': source_key(wikimapia_url),
            'title': 'Храм Спаса Нерукотворного Образа в Клязьме (Пушкино)',
            'latitude': 55.9769591,
            'longitude': 37.8377935,
        },
    )
    photos = [
        {
            'title': yandex['title'],
            'engine': 'yandex_maps',
            'source_url': yandex_url,
            'query': yandex_url,
            'gallery_scope': 'organization',
            'gallery_source_key': source_key(yandex_url),
            'image_url': 'https://example.org/yandex-photo.jpg',
        },
        {
            'title': wikimapia['title'],
            'engine': 'wikimapia',
            'source_url': wikimapia_url,
            'query': wikimapia_url,
            'image_url': 'https://photos.wikimapia.org/p/00/01/02/03/04_big.jpg',
        },
    ]

    report = verify_report({'items': [yandex, wikimapia], 'photos': photos}, place, [])

    assert {row['status'] for row in report['verification']['sources']} == {'accepted'}
    assert {row['status'] for row in report['verification']['photos']} == {'accepted'}
    assert {photo['engine'] for photo in report['photos']} == {'yandex_maps', 'wikimapia'}

    wrong_location = dict(wikimapia, page_identity=dict(
        wikimapia['page_identity'], latitude=56.2,
    ))
    assert verify_source(place, wrong_location).status == 'rejected'


def test_townhouse_conflict_and_historical_article():
    place = {'name': 'Рождествено', 'description': 'Информация об усадьбе', 'region': 'Московская область'}
    wrong = item('Посёлок таунхаусов Рождествено', url=SOURCE)
    wrong['snippet'] = 'Рядом усадьба Рождествено'
    assert verify_source(place, wrong, [SOURCE]).status == 'rejected'
    right = item('Усадьба Рождествено', url=SOURCE)
    right['snippet'] = 'Неподалёку таунхаусы'
    assert verify_source(place, right, [SOURCE]).status == 'accepted'


def test_primary_page_does_not_read_publisher_sidebar_or_other_graph_objects():
    html = '''<title>Убежище</title><main><h1>Убежище</h1><p>Описание</p>
    <aside>улица Дубровская, дом 6</aside></main><footer>улица Чужая</footer>
    <script type="application/ld+json">{"@type":"Organization","address":"улица Чужая, дом 6"}</script>
    <script type="application/ld+json">{"@graph":[{"@type":"Place","address":"улица Чужая, дом 6"}]}</script>'''
    data = extract_page_identity(html, 'https://example.org/object')
    assert 'Чужая' not in data['text'] and 'Дубровская' not in data['text']
    assert 'address' not in data
    html += '''<script type="application/ld+json">{"@type":"WebPage","mainEntity":{"@type":"Place","name":"Убежище","address":{"streetAddress":"улица Юлиана Семенова, дом 6","addressLocality":"Москва"},"geo":{"latitude":55.64085,"longitude":37.39277}}}</script>'''
    data = extract_page_identity(html, 'https://example.org/object')
    assert data['latitude'] == 55.64085
    assert verify_source(PLACE, item(page_identity=data)).status == 'accepted'


def test_gallery_provenance_and_cache_are_rechecked():
    reference = item(url=SOURCE)
    gallery = dict(title='Фото объекта', source_url=SOURCE, image_url='https://example.org/gallery.jpg',
                   query=SOURCE, engine='wikimapia')
    searched = dict(gallery, image_url='https://example.org/search.jpg', engine='bing', query='убежище москва')
    wrong = item('Убежище, Москва, 1-я Дубровская ул., 6')
    report = osint._refilter_report({'items': [reference, wrong], 'photos': [gallery, searched], 'assessment': {}}, PLACE)
    assert len(report['items']) == 1
    assert report['photos'] == [gallery]
    assert report['assessment'] == osint.assess_osint_items(report['items'])
    assert any(row['status'] != 'accepted' for row in report['verification']['sources'])
    assert osint._refilter_report(json.loads(json.dumps(report)), PLACE) == report
    changed = dict(PLACE, description='')
    revised = osint._refilter_report(report, changed)
    assert revised['photos'] == []
    assert revised['items'] == []


def test_numeric_identity_does_not_confuse_dates_or_partial_numbers():
    place = {'name': 'СПТУ-23', 'region': 'Владимирская область'}
    assert verify_source(place, item('СПТУ-230, Владимирская область')).status == 'rejected'
    assert verify_source(place, item('СПТУ-23, Владимирская область')).status == 'accepted'


@pytest.mark.parametrize('title', [
    'Радиоцентр № 9, производственное предприятие, Московская область, Богородский городской округ',
    'Бывший 11 (теперь 9й) радиоцентр / Виварий',
])
def test_numbered_radio_center_sources_match_current_object(title):
    place = {
        'name': 'Радиоцентр № 9',
        'description': 'Отделение «Радиоцентр №9». Передающая средневолновая антенна-мачта.',
        'full_address': '«Волга», Богородский городской округ, Московская область',
        'latitude': 55.83583,
        'longitude': 38.34333,
    }
    assert verify_source(place, item(title)).status == 'accepted'


def test_numbered_radio_center_match_survives_offset_source_coordinates():
    place = {
        'name': 'Радиоцентр № 9',
        'description': 'Отделение «Радиоцентр №9». Передающая средневолновая антенна-мачта.',
        'full_address': '«Волга», Богородский городской округ, Московская область',
        'latitude': 55.83583,
        'longitude': 38.34333,
    }
    row = primary(
        item('Заброшенный радиоцентр № 9 ФГУП «РТРС» — Электроугли'),
        latitude=55.70,
        longitude=38.20,
    )
    assert verify_source(place, row).status == 'accepted'
    assert verify_source(place, item('Радиоцентр № 11, Московская область')).status == 'unconfirmed'
    assert verify_source(place, item('Радиоцентр № 9, Тверская область')).status == 'rejected'


def test_numbered_radio_center_sources_appear_in_confirmed_report():
    place = {
        'name': 'Радиоцентр № 9',
        'description': 'Отделение «Радиоцентр №9». Передающая средневолновая антенна-мачта.',
        'full_address': '«Волга», Богородский городской округ, Московская область',
        'latitude': 55.83583,
        'longitude': 38.34333,
    }
    candidates = [
        item('Радиоцентр № 9, производственное предприятие, Московская область, Богородский городской округ',
             url='https://example.org/radio-center-9'),
        item('Бывший 11 (теперь 9й) радиоцентр / Виварий',
             url='https://example.org/former-radio-center-11'),
        primary(item('Заброшенный радиоцентр № 9 ФГУП «РТРС» — Электроугли',
                     url='https://example.org/radio-center-9-electrougli'),
                 latitude=55.70, longitude=38.20),
    ]
    report = osint._refilter_report({'items': candidates, 'photos': []}, place)
    assert report['items'] == candidates
    assert all(row['status'] == 'accepted' for row in report['verification']['sources'])


def test_generic_factory_matches_exact_named_neighborhood_but_not_city_only():
    place = {
        'name': 'Небольшой заброшенный завод',
        'full_address': 'Дальняя улица, Керамик, Балашиха, городской округ Балашиха, Московская область',
        'description': 'Завод с территорией 150 на 200 метров.',
    }
    local_source = item('Завод «Керамик» (Московская область)',
                        url='https://urban3p.ru/object28395')
    city_only_source = item('Заброшенный завод в Балашихе',
                            url='https://example.org/balashikha-factory')
    assert verify_source(place, local_source).status == 'accepted'
    assert verify_source(place, city_only_source).status == 'unconfirmed'
    photo = {
        'title': local_source['title'],
        'source_url': local_source['url'],
        'image_url': 'https://img04.urban3p.ru/up/o/28395/photo.jpg',
        'engine': 'urban3p',
        'query': local_source['url'],
    }
    report = verify_report({'items': [local_source], 'photos': [photo]}, place, [])
    assert report['items'] == [local_source]
    assert report['photos'] == [photo]


def test_page_metadata_cannot_be_borrowed_from_another_url():
    row = primary(item(), address='улица Юлиана Семенова, дом 6')
    row['url'] = 'https://example.org/other'
    assert verify_source(PLACE, row).status == 'unconfirmed'


def test_region_and_city_conflicts_override_same_street_and_house():
    place = dict(PLACE, full_address='улица Юлиана Семенова, дом 6, город Москва')
    row = primary(item(), address='улица Юлиана Семенова, дом 6', locality='Тверь')
    assert verify_source(place, row).status == 'rejected'
    row = primary(item(), address='улица Юлиана Семенова, дом 6, Тверская область')
    place['full_address'] = 'улица Юлиана Семенова, дом 6, Московская область'
    assert verify_source(place, row).status == 'rejected'


def test_direct_link_remains_photo_not_promoted_source():
    url = 'https://photos.wikimapia.org/p/00/08/50/63/08_1280.jpg'
    report = osint._refilter_report({'items': [], 'photos': []}, dict(PLACE, description=url))
    assert report['items'] == []
    assert [p['image_url'] for p in report['photos']] == [url]


def test_new_report_and_cached_report_share_the_gate(monkeypatch):
    monkeypatch.setattr(osint, 'description_photos_for_links', lambda *args, **kwargs: [])
    monkeypatch.setattr(osint, 'vk_sources_for_links', lambda *args, **kwargs: [])
    fresh = osint.build_osint_report('', '', PLACE)
    assert fresh['verification']['version'] == VERSION
    cached = osint._refilter_report(fresh, PLACE)
    assert cached['items'] == fresh['items']
    assert cached['verification'] == fresh['verification']


def test_search_results_are_audited_and_unverified_pages_are_not_scraped(monkeypatch):
    wrong = item('Убежище, Москва, Дубровская улица', score=1, query='убежище')
    monkeypatch.setattr(osint, '_search_soft', lambda *args: (wrong,) if args[-1] == 'general' else ())
    monkeypatch.setattr(osint, 'enrich_candidates', lambda place, rows, refs: rows)
    monkeypatch.setattr(osint, 'description_photos_for_links', lambda *args, **kwargs: [])
    monkeypatch.setattr(osint, 'vk_sources_for_links', lambda *args, **kwargs: [])
    fetched = []
    def gallery(links, *args, **kwargs):
        fetched.extend(link['url'] for link in links)
        return []
    monkeypatch.setattr(osint, 'site_photos_for_links', gallery)
    monkeypatch.setattr(osint, 'urban3p_photos_for_links', gallery)
    fresh = osint.build_osint_report('https://search.example', '', PLACE)
    assert wrong['url'] not in fetched
    assert len(fresh['items']) == 1
    assert any(row['candidate']['url'] == wrong['url'] and row['status'] != 'accepted'
               for row in fresh['verification']['sources'])


def test_enrichment_does_not_fetch_unknown_hosts_and_failures_are_soft(monkeypatch):
    from urbex.infrastructure import osint_evidence as evidence
    monkeypatch.setattr(evidence.httpx, 'Client', lambda **kwargs: (_ for _ in ()).throw(AssertionError('No request expected')))
    for url in ['http://127.0.0.1/private', 'https://wikimapia.org.evil.example/1',
                'https://wikimapia.org:9000/1', 'https://user:pass@wikimapia.org/1']:
        assert evidence._fetch(url) is None
    rows = evidence.enrich_candidates(PLACE, [item()], [])
    assert rows == [item()]


def test_article_gallery_excludes_sidebar_ads_and_comments():
    from urbex.infrastructure.osint_description import _extract_generic_image_urls
    url = 'https://example.org/manor'
    html = '''<img src="/header.jpg"><article><img src="/manor.jpg">
    <aside><img src="/nearby.jpg"></aside><div class="related"><img src="/other.jpg"></div>
    <div class="comments"><img src="/avatar.jpg"></div></article><footer><img src="/footer.jpg"></footer>'''
    assert _extract_generic_image_urls(html, url) == ['https://example.org/manor.jpg']


def test_unscoped_generic_page_images_are_not_a_gallery():
    url = 'https://example.org/manor'
    photo = {'title': 'Усадьба', 'source_url': url, 'image_url': 'https://example.org/banner.jpg',
             'engine': 'web_page', 'query': url, 'gallery_scope': 'unknown'}
    result = verify_report({'items': [item('Усадьба', url)], 'photos': [photo]},
                           {'name': 'Усадьба'}, [url])
    assert result['photos'] == []
    assert result['verification']['photos'][0]['status'] == 'unconfirmed'


def test_street_and_house_without_settlement_are_insufficient():
    row = primary(item(), address='улица Юлиана Семенова, дом 6')
    assert verify_source(PLACE, row).status == 'unconfirmed'


@pytest.mark.parametrize('name', ['Пионерлагерь «Голубой Факел»', 'Пионерлагеря «Голубой Факел»'])
def test_compound_camp_name_accepts_matching_map_gallery(name):
    place = dict(name=name, latitude=55.323611, longitude=37.778627)
    url = 'https://yandex.ru/maps/org/goluboy_fakel/123456/'
    row = primary(item('Пионерский лагерь Голубой факел', url=url),
                  latitude=place['latitude'], longitude=place['longitude'])
    photo = dict(source_url=url, image_url='https://example.org/camp.jpg',
                 engine='yandex_maps', gallery_scope='organization',
                 gallery_source_key=source_key(url), page_identity=row['page_identity'])
    report = verify_report(dict(items=[row], photos=[photo]), place, [])
    assert report['photos'] == [photo]
    assert report['items'] == [row]
    row['page_identity']['latitude'] = 56.0
    assert verify_source(place, row).status == 'rejected'
    row['page_identity']['latitude'] = place['latitude']
    row['title'] = 'Пионерский лагерь Красный факел'
    assert verify_source(place, row).status == 'unconfirmed'


def test_camp_real_map_offset_and_structured_district_address():
    from urbex.infrastructure.osint_identity import locality_cues
    place = dict(name='Пионерлагерь «Голубой Факел»', latitude=55.323611,
                 longitude=37.778627, full_address='Красное, городской округ Домодедово, Московская область')
    url = 'https://yandex.com/maps/org/pionerskiy_lager_goluboy_fakel/170329852852/'
    row = primary(item('Пионерский лагерь Голубой факел', url=url),
                  latitude=55.32419, longitude=37.779987,
                  address='Московская область, Домодедово, микрорайон Белые Столбы, территория Радуга')
    assert locality_cues(place['full_address']) == {'домодедово'}
    assert verify_source(place, row).status == 'accepted'
    row['page_identity']['address'] = 'Московская область, городской округ Клин'
    assert verify_source(place, row).status == 'unconfirmed'
    row['page_identity']['address'] = 'Московская область, Домодедово'
    row['page_identity']['latitude'] = 56.0
    assert verify_source(place, row).status == 'rejected'


def test_exact_abbreviated_camp_title_matches_without_manual_reference():
    place = {
        'name': 'Заброшенный п/л под Истрой',
        'category': 'разное',
        'description': 'Заброшенный пионерский лагерь.',
        'full_address': 'Буньково, муниципальный округ Истра, Московская область',
        'latitude': 55.8907,
        'longitude': 36.8257,
    }
    candidate = item(
        'Заброшенный п/л под Истрой (Московская область) / Архив',
        url='https://urban3p.ru/object1593/',
    )
    assert verify_source(place, candidate).status == 'accepted'
    assert verify_source(
        place,
        item('Заброшенный п/л под Истрой — Urban3P',
             url='https://urban3p.ru/object1593/'),
    ).status == 'accepted'
    assert verify_source(
        place,
        item('Заброшенный п/л под Подольском (Московская область) / Архив',
             url='https://urban3p.ru/object26631'),
    ).status == 'unconfirmed'
    assert verify_source(
        place,
        item('Заброшенный завод под Истрой (Московская область) / Архив',
             url='https://urban3p.ru/object26631'),
    ).status == 'rejected'


def test_named_airfield_source_matches_within_large_site_bounds():
    place = {
        'name': 'Аэродром ермолино',
        'category': 'разное',
        'full_address': 'Ермолино, Боровский муниципальный округ, Калужская область',
        'latitude': 55.220799,
        'longitude': 36.606617,
    }
    url = 'https://ru.wikipedia.org/wiki/Ермолино_(аэродром)'
    source = primary(
        item('Ермолино (аэродром)', url=url),
        title='Ермолино (аэродром)',
        text='Ермолино — военный аэродром совместного базирования, расположен в городе Ермолино.',
        latitude=55.223934,
        longitude=36.609792,
    )
    assert verify_source(place, source).status == 'accepted'
    source['page_identity']['latitude'] = 57.0
    assert verify_source(place, source).status == 'rejected'
    source['page_identity']['latitude'] = 55.223934
    source['title'] = 'Вертолётный центр Ермолино'
    source['page_identity']['title'] = 'Вертолётный центр Ермолино'
    assert verify_source(place, source).status == 'unconfirmed'


def test_accepted_exact_title_wikimapia_candidate_still_fetches_coordinates(monkeypatch):
    place = {
        'name': 'Заброшенный детский сад',
        'category': 'разное',
        'full_address': '113, Трубино, городской округ Щёлково, Московская область',
        'latitude': 55.992,
        'longitude': 38.1273,
    }
    url = 'https://wikimapia.org/14892051/ru/Заброшенный-детский-сад'
    candidate = item('Заброшенный детский сад - Икша', url=url)
    identity = {
        'source_key': source_key(url),
        'title': 'Заброшенный детский сад (Икша)',
        'latitude': 56.1870754,
        'longitude': 37.5090153,
    }
    assert verify_source(place, candidate).status == 'accepted'
    monkeypatch.setattr(osint_evidence, '_fetch', lambda _url: identity)

    enriched = osint_evidence.enrich_candidates(place, [candidate], [])

    assert enriched[0]['page_identity'] == identity
    assert verify_source(place, enriched[0]).status == 'rejected'


def test_pdrc_abbreviation_matches_same_site_wikimapia_object():
    place = {
        'name': 'Пдрц',
        'category': 'разное',
        'description': 'Здесь находились КВ-передатчики, подключенные к антеннам РГД.',
        'full_address': 'городской округ Солнечногорск, Московская область',
        'latitude': 56.082651,
        'longitude': 37.089576,
    }
    url = 'https://wikimapia.org/5129849/ru/Техническое-здание-ПДРЦ-№1'
    candidate = primary(
        item('Техническое здание ПДРЦ №1 - Wikimapia', url=url),
        title='Техническое здание ПДРЦ №1',
        latitude=56.0826923,
        longitude=37.0896894,
    )
    assert verify_source(place, candidate).status == 'accepted'
    candidate['page_identity']['latitude'] = 57.0
    assert verify_source(place, candidate).status == 'rejected'


def test_openly_licensed_wikipedia_photo_is_added_from_search_result(monkeypatch):
    place = {
        'id': 42,
        'name': 'Аэродром Ермолино',
        'category': 'разное',
        'full_address': 'Ермолино, Боровский муниципальный округ, Калужская область',
        'latitude': 55.220799,
        'longitude': 36.606617,
    }
    url = 'https://ru.wikipedia.org/wiki/Ермолино_(аэродром)'
    identity = {
        'source_key': source_key(url),
        'title': 'Ермолино (аэродром)',
        'text': 'Военный аэродром расположен в Ермолино.',
        'latitude': 55.223934,
        'longitude': 36.609792,
    }
    candidate = dict(item('Ермолино (аэродром)', url=url), score=0)
    photo = {
        'title': 'Площадь перед КПП аэродрома Ермолино',
        'image_url': 'https://upload.wikimedia.org/wikipedia/commons/ermolino.jpg',
        'source_url': url,
        'engine': 'web_page',
        'query': url,
        'gallery_scope': 'primary',
        'page_identity': identity,
        'attribution': 'Wikimedia Commons · Автор · CC BY-SA 4.0',
        'score': 0,
    }
    monkeypatch.setattr(
        osint, '_search_soft',
        lambda _url, _origin, _query, category: (candidate,) if category == 'general' else (),
    )
    monkeypatch.setattr(osint, 'enrich_candidates',
                        lambda _place, rows, _refs: [dict(row, page_identity=identity) for row in rows])
    monkeypatch.setattr(osint, 'description_photos_for_links', lambda *args, **kwargs: [])
    monkeypatch.setattr(osint, 'vk_sources_for_links', lambda *args, **kwargs: [])
    monkeypatch.setattr(osint, 'urban3p_photos_for_links', lambda *args, **kwargs: [])
    monkeypatch.setattr(osint, 'site_photos_for_links', lambda *args, **kwargs: [])
    monkeypatch.setattr(osint, 'wikipedia_photos_for_sources', lambda *args, **kwargs: [photo])

    report = osint.build_osint_report('https://search.example', '', place)
    assert report['items'][0]['url'] == url
    assert report['photos'] == [photo]
    assert report['verification']['photos'][0]['status'] == 'accepted'


def test_cached_report_recovers_linked_urban_gallery(monkeypatch):
    place = dict(PLACE, id=42, description='https://urban3p.com/object42/gallery')
    photo = {'engine': 'urban3p', 'source_url': 'https://urban3p.ru/object42',
             'query': 'https://urban3p.ru/object42',
             'image_url': 'https://img01.urban3p.ru/up/o/42/gallery/123.jpg'}
    monkeypatch.setattr(osint, 'load_osint_report', lambda *args: {'items': [], 'photos': []})
    monkeypatch.setattr(osint, 'urban3p_photos_for_links', lambda *args: [photo])
    monkeypatch.setattr(osint, 'save_osint_report', lambda engine, id, report: report)
    result = osint.get_or_build_osint_report(None, '', '', place)
    assert result['photos'] == [photo]
    assert result['urban3p_photos_checked_at'] > 0


def test_source_photos_loads_vk_urban3p_and_wikimapia_links(monkeypatch):
    from urbex.infrastructure import source_photos as galleries

    links = (
        'https://vk.com/album-97053640_272983075',
        'https://www.urban3p.ru/object9229',
        'https://wikimapia.org/17109228/ru',
    )
    place = dict(PLACE, description='\n'.join(links))
    fetched = []

    def gallery(engine, link):
        fetched.append(link)
        return [{
            'title': 'Фото объекта',
            'source_url': link,
            'query': link,
            'image_url': f'https://images.example/{engine}.jpg',
            'engine': engine,
        }]

    monkeypatch.setattr(
        galleries, 'urban3p_photos_for_links',
        lambda source_links, limit: gallery('urban3p', source_links[0]['url']),
    )
    monkeypatch.setattr(
        galleries, 'vk_photos_for_links',
        lambda token, source_links, limit: gallery('vk', source_links[0]['url']),
    )
    monkeypatch.setattr(
        galleries, 'wikimapia_photos_for_links',
        lambda source_links, limit: gallery('wikimapia', source_links[0]['url']),
    )

    photos = galleries.source_photos(place)

    assert set(fetched) == set(links)
    assert {photo['engine'] for photo in photos} == {'vk', 'urban3p', 'wikimapia'}


def test_incomplete_source_photo_cache_retries_missing_gallery(monkeypatch):
    from urbex.infrastructure import source_photos as galleries
    monkeypatch.setattr(galleries, 'discover_photos', lambda *a: [])

    links = (
        'https://vk.com/album-97053640_272983075',
        'https://www.urban3p.ru/object9229',
        'https://wikimapia.org/17109228/ru',
    )
    place = dict(PLACE, description='\n'.join(links))
    clock = [0]
    wikimapia_calls = []
    monkeypatch.setattr(galleries, 'monotonic', lambda: clock[0])
    galleries._cache.clear()

    def photo(engine, link):
        return [{
            'title': 'Фото объекта',
            'source_url': link,
            'query': link,
            'image_url': f'https://images.example/{engine}.jpg',
            'engine': engine,
        }]

    monkeypatch.setattr(
        galleries, 'urban3p_photos_for_links',
        lambda source_links, limit: photo('urban3p', source_links[0]['url']),
    )
    monkeypatch.setattr(
        galleries, 'vk_photos_for_links',
        lambda token, source_links, limit: photo('vk', source_links[0]['url']),
    )
    monkeypatch.setattr(
        galleries, 'wikimapia_photos_for_links',
        lambda source_links, limit: wikimapia_calls.append(source_links[0]['url']) or [],
    )

    galleries.source_photos(place)
    clock[0] = 31
    galleries.source_photos(place)

    assert wikimapia_calls == [links[2], links[2]]
    galleries._cache.clear()
