import json
import pytest
from urbex.infrastructure.osint_identity import source_key, verify_source, verify_report, extract_page_identity
from urbex.infrastructure import osint

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
    assert fresh['verification']['version'] == 5
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
