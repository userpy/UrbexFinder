import pytest
from urbex.infrastructure import osint, osint_description as description
from urbex.infrastructure.osint_identity import primary_gallery, catalog_gallery_matches

PAGE = 'http://podmoskovnye.ru/usadba/ysadbi-rossii-po-oblastyam-i-regionam/135-yaroslavskaya/209-shill'
PHOTO = 'http://podmoskovnye.ru/images/stories/photos/yaroslavskaya/shill/Главный%20дом..jpg'


@pytest.mark.parametrize('attributes', ['itemprop="articleBody"', 'class="item-page"', 'class="entry-content"'])
def test_cms_article_is_a_gallery_but_sidebar_is_not(attributes):
    html = f'''<div class="header"><img src="/logo.jpg"></div>
    <div {attributes}><p>Фото июнь 2013.</p><img src="{PHOTO}">
    <aside><img src="/nearby.jpg"></aside><div class="comments"><img src="/avatar.jpg"></div>
    </div><footer><img src="/footer.jpg"></footer>'''
    assert primary_gallery(html, PAGE) == (True, [PHOTO])


def test_old_parsed_shill_gallery_is_recovered_without_search_or_network():
    photo = {'title': 'Шилля усадьба', 'source_url': PAGE, 'image_url': PHOTO,
             'query': PAGE, 'engine': 'web_page', 'gallery_scope': 'unknown'}
    place = {'name': 'Шилля усадьба', 'description': f'Информация об усадьбе ({PAGE})'}
    payload = {'items': [], 'photos': [], 'verification': {'photos': [
        {'candidate': photo, 'status': 'unconfirmed', 'reasons': ['Old rule']}
    ]}}
    result = osint._refilter_report(payload, place)
    assert result['photos'] == [photo]
    assert result['items'][0]['url'] == PAGE
    assert result['verification']['photos'][0]['status'] == 'accepted'
    assert description.links_from_description(place['description'])[0]['title'] == PAGE


@pytest.mark.parametrize('image', [
    PHOTO.replace('/shill/', '/other/'),
    PHOTO.replace('/yaroslavskaya/', '/tverskaya/'),
    PHOTO.replace('podmoskovnye.ru/', 'podmoskovnye.ru.evil.example/'),
    'http://podmoskovnye.ru/images/logo.jpg',
    PHOTO.replace('/shill/', '/shill/../other/'),
])
def test_catalog_directory_does_not_accept_neighbours_or_foreign_hosts(image):
    assert not catalog_gallery_matches({'source_url': PAGE, 'image_url': image})


def test_catalog_image_alone_does_not_bypass_source_or_scraper_provenance():
    photo = {'title': 'Шилля усадьба', 'source_url': PAGE, 'image_url': PHOTO,
             'query': 'усадьба Шилля', 'engine': 'bing images'}
    place = {'name': 'Шилля усадьба', 'description': PAGE}
    assert osint._refilter_report({'photos': [photo]}, place)['photos'] == []
    photo.update(query=PAGE, engine='web_page')
    assert osint._refilter_report({'photos': [photo]}, {'name': 'Шилля усадьба'})['photos'] == []


def test_main_gallery_recovers_only_verified_estate_photos_from_saved_report(monkeypatch):
    from urbex.infrastructure import source_photos as sources
    monkeypatch.setattr(sources, 'generic_page_photos_for_links',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('No network needed')))
    photo = {'title': 'Шилля усадьба', 'source_url': PAGE, 'image_url': PHOTO,
             'query': PAGE, 'engine': 'web_page', 'gallery_scope': 'unknown'}
    wrong = dict(photo, image_url=PHOTO.replace('/shill/', '/other/'))
    report = {'photos': [], 'verification': {'photos': [
        {'candidate': p, 'status': 'unconfirmed'} for p in [wrong, photo]
    ]}}
    assert sources.source_photos({'name': 'Шилля усадьба', 'description': PAGE}, report) == [photo]


def test_description_link_overrides_conflicting_identity_and_recovers_gallery():
    from urbex.infrastructure.osint_identity import source_key
    photo = {'title': 'Шилля усадьба', 'source_url': PAGE, 'image_url': PHOTO,
             'query': PAGE, 'engine': 'web_page', 'gallery_scope': 'primary',
             'page_identity': {'source_key': source_key(PAGE), 'title': 'Шилля усадьба',
                               'address': 'Ярославская область', 'latitude': 57, 'longitude': 39}}
    place = {'name': 'Завод', 'full_address': 'Московская область',
             'latitude': 55, 'longitude': 37,
             'description': PAGE.replace('http://', 'https://www.')}
    report = {'photos': [], 'verification': {'photos': [
        {'candidate': photo, 'status': 'rejected', 'reasons': ['Не совпадает тип объекта']}
    ]}}
    result = osint._refilter_report(report, place)
    assert result['photos'] == [photo]
    assert result['verification']['sources'][0]['status'] == 'accepted'
    assert result['verification']['sources'][0]['evidence'] == ['reference']
    assert osint._refilter_report(report, dict(place, description=''))['photos'] == []


def test_description_link_does_not_confirm_other_estates_or_lookalike_hosts():
    from urbex.infrastructure.osint_identity import verify_source
    place = {'name': 'Завод'}
    assert verify_source(place, {'url': PAGE, 'title': 'Усадьба'},
                         [PAGE.replace('209-shill', '210-other')]).status == 'rejected'
    fake = PAGE.replace('podmoskovnye.ru', 'podmoskovnye.ru.evil.example')
    assert verify_source(place, {'url': fake, 'title': 'Усадьба'}, [fake]).status == 'rejected'
