import pytest
from urllib.parse import quote
from urbex.infrastructure import osint


@pytest.mark.parametrize('title', [
    'Убежище гражданской обороны — Википедия',
    'Бомбоубежище — Википедия',
    'Убежище гражданской обороны',
    'Фото двери убежища',
])
def test_generic_shelter_article_and_its_images_are_removed_from_cached_report(title):
    place = {'name': 'Убежище', 'region': 'Москва',
             'full_address': '1-я Новокузьминская улица, Москва'}
    url = 'https://ru.wikipedia.org/wiki/' + quote('Убежище_гражданской_обороны')
    unrelated = {
        'title': title, 'snippet': 'Москва, история гражданской обороны',
        'url': url, 'source_url': url,
        'image_url': 'https://upload.wikimedia.org/wikipedia/commons/door.jpg',
    }
    relevant = {
        'title': 'Больше не работает: Убежище, Москва, 1-я Новокузьминская',
        'url': 'https://example.org/shelter/123',
        'source_url': 'https://example.org/shelter/123',
        'image_url': 'https://example.org/entrance.jpg',
    }
    place['description'] = relevant['url']
    relevant.update(engine='web_page', query=relevant['url'], gallery_scope='primary')
    report = osint._refilter_report({
        'items': [unrelated, relevant], 'photos': [unrelated, relevant],
    }, place)
    assert report['items'] == [relevant]
    assert report['photos'] == [relevant]
    assert report['total'] == report['photos_total'] == 1


@pytest.mark.parametrize('filename', [
    '40px-Ambox_important.svg.png', 'Question_book-new.svg',
    '50px-Commons-logo.svg.png', 'Disambig.svg',
])
def test_service_icons_are_not_object_photos(filename):
    photo = {'title': 'Убежище в Москве',
             'image_url': 'https://upload.wikimedia.org/wikipedia/commons/' + filename}
    assert osint._filter_photos([photo], {'name': 'Убежище', 'region': 'Москва'}) == []


def test_specific_shelter_wikipedia_article_is_not_blocked():
    item = {'title': 'Бункер Сталина — Википедия',
            'url': 'https://ru.wikipedia.org/wiki/' + quote('Бункер_Сталина'),
            'image_url': 'https://upload.wikimedia.org/wikipedia/commons/entrance.jpg'}
    assert not osint._is_junk_source(item)
    assert not osint._is_junk_photo(item)


@pytest.mark.parametrize('publisher', ['fire.info', 'www.fire.info', 'reference.example'])
def test_generic_shelter_publisher_suffix_does_not_identify_an_object(publisher):
    place = {'name': 'Убежище', 'region': 'Москва',
             'full_address': '1-я Дубровская улица, Москва'}
    unrelated = {
        'title': f'Убежище гражданской обороны - {publisher}',
        'url': 'https://fire.info/shelter', 'source_url': 'https://fire.info/shelter',
        'image_url': 'https://fire.info/forest.jpg',
    }
    relevant = {
        'title': 'Убежище, гражданская оборона, Москва, 1-я Дубровская ул., 6 — Яндекс Карты',
        'url': 'https://yandex.ru/maps/org/123',
        'source_url': 'https://yandex.ru/maps/org/123',
        'image_url': 'https://example.org/entrance.jpg',
    }
    place['description'] = relevant['url']
    relevant.update(engine='web_page', query=relevant['url'], gallery_scope='primary')
    report = osint._refilter_report({'items': [unrelated, relevant],
                                    'photos': [unrelated, relevant]}, place)
    assert report['items'] == [relevant]
    assert report['photos'] == [relevant]


def test_shelter_address_after_dash_is_preserved():
    assert not osint._is_junk_source({
        'title': 'Убежище — Москва, 1-я Дубровская ул., 6',
        'url': 'https://example.org/shelter',
    })


@pytest.mark.parametrize('region', ['', 'Тверская область'])
def test_campus_acronym_is_required_in_external_sources(region):
    place = {'name': 'Заброшенные корпуса ТГСА', 'region': region}
    def item(title):
        return {'title': title, 'url': 'https://urban3p.com/object123',
                'source_url': 'https://urban3p.com/object123/gallery',
                'image_url': 'https://img04.urban3p.ru/up/o/123/photo.jpg',
                'engine': 'urban3p'}
    wrong = [item('Заброшенные корпуса санатория'),
             item('Заброшенные корпуса психиатрической больницы')]
    right = item('Заброшенные корпуса ТГСА — Тверская область')
    assert osint._unique_name_tokens(place['name']) == {'тгса'}
    assert osint._filter_photos(wrong + [right], place) == [right]
    assert osint._filter_sources(wrong + [right], place) == [right]
    # A name/acronym match alone no longer confirms a cached gallery.
    assert osint._refilter_report({'photos': wrong + [right]}, place)['photos'] == []


def test_short_acronym_is_not_discarded_for_longer_generic_words():
    assert osint._unique_name_tokens('Корпуса МГУ') == {'мгу'}
    assert osint._unique_name_tokens('корпуса тгса') == {'тгса'}


@pytest.mark.parametrize('title', ['СПТУ-23', 'СПТУ №23', 'спту 23', 'СПТУ — 23'])
def test_numbered_institution_requires_complete_number(title):
    place = {'name': 'СПТУ-23', 'region': 'Владимирская область'}
    def item(name):
        return {'title': name, 'snippet': 'Дата 23.10.2022', 'engine': 'swalker',
                'url': 'https://swalker.ru/23.html',
                'source_url': 'https://swalker.ru/23.html',
                'image_url': 'https://swalker.ru/23.jpg'}
    right = item(title)
    wrong = [item('СПТУ-3'), item('СПТУ-230'), item('СПТУ-123'), item('СПТУ')]
    assert osint._filter_sources(wrong + [right], place) == [right]
    assert osint._filter_photos(wrong + [right], place) == [right]
    # The caption has no locality or primary-source evidence.
    assert osint._refilter_report({'items': wrong + [right]}, place)['items'] == []


def test_summer_kindergarten_does_not_match_age_in_biography():
    place = {'name': 'Летний детский сад', 'region': 'Московская область'}
    biography = {'title': 'Ян, Василий Григорьевич — Википедия',
                 'snippet': 'Под Сталинградом погиб 21-летний Игорь. Из Москвы пришло известие.',
                 'url': 'https://ru.wikipedia.org/wiki/Writer', 'engine': 'duckduckgo'}
    kindergarten = {'title': 'Летний детский сад №1985 (Московская область)',
                    'snippet': 'Работал до 2009 года.',
                    'url': 'https://urban3p.ru/object28021', 'engine': 'duckduckgo'}
    assert osint._filter_sources([biography, kindergarten], place) == [kindergarten]
    # A generic kindergarten name and oblast do not establish object identity.
    assert osint._refilter_report({'items': [biography, kindergarten]}, place)['items'] == []
    photo = dict(biography, source_url=biography['url'], image_url='https://example.org/portrait.jpg')
    assert osint._filter_photos([photo], place) == []
    inflected = dict(kindergarten, title='Фото летнего детского сада №1985')
    assert osint._filter_sources([inflected], place) == [inflected]


def test_shelter_report_requires_object_identity_not_shared_city():
    source = 'http://wikimapia.org/38437817/ru/Убежище-гражданской-обороны'
    place = {
        'name': 'Убежище гражданской обороны (ru)',
        'region': 'Москва',
        'full_address': 'улица Юлиана Семёнова, район Солнцево, Москва',
        'description': source,
    }
    wrong = [
        {'title': title, 'url': 'https://example.org/object',
         'source_url': 'https://example.org/object',
         'image_url': 'https://example.org/entrance.jpg'}
        for title in [
            'Бомбоубежище - Москва | Объект гражданской обороны',
            'Бомбоубежище в городе Москва',
            'Стандартное убежище ГО (Москва) / Подземное',
            'Убежище, гражданская оборона, Москва, 1-я Дубровская ул., 6 — Яндекс Карты',
            'Убежище гражданской обороны - fire.info',
        ]
    ]
    report = osint._refilter_report({'items': wrong, 'photos': wrong,
                                   'assessment': {}}, place)
    assert [item['url'] for item in report['items']] == [source]
    assert report['photos'] == []
    assert report['assessment'] == osint.assess_osint_items(report['items'])
    assert osint._matches_shelter_identity({
        'source_url': 'https://wikimapia.org/38437817/en/Shelter',
    }, place)
    assert osint._matches_shelter_identity({
        'title': 'Убежище на улице Юлиана Семенова, Москва',
    }, place)
    assert not osint._matches_shelter_identity({
        'source_url': 'https://wikimapia.org/384378170/en/Shelter',
    }, place)


def test_generic_shelter_without_address_does_not_match_city_alone():
    assert osint._filter_sources([{
        'title': 'Убежище, Москва, Дубровская улица',
        'url': 'https://example.org/object',
    }], {'name': 'Убежище гражданской обороны (ru)', 'region': 'Москва'}) == []


@pytest.mark.parametrize('place', [
    {'name': 'Усадьба Рождествено', 'region': 'Московская область'},
    {'name': 'Рождествено', 'region': 'Московская область',
     'description': 'Информация об усадьбе http://podmoskovnye.ru/usadba/example'},
    {'name': 'Рождествено', 'region': 'Московская область', 'category_name': 'Усадьбы'},
])
@pytest.mark.parametrize('title', [
    'Посёлок таунхаусов Рождествено - Москва - Wikimapia',
    'Коттеджный поселок Рождествено',
    'Жилой комплекс Рождествено',
    'ЖК Рождествено',
])
def test_manor_does_not_match_namesake_housing(place, title):
    wrong = {'title': title, 'snippet': 'Рядом находится усадьба Рождествено.',
             'url': 'https://wikimapia.org/179731',
             'source_url': 'https://wikimapia.org/179731',
             'image_url': 'https://example.org/townhouses.jpg'}
    right = {'title': 'Усадьба «Рождествено» - Рождествено',
             'snippet': 'Усадебный дом XVIII века. Неподалёку построен посёлок таунхаусов.',
             'url': 'https://wikimapia.org/17184089',
             'source_url': 'https://wikimapia.org/17184089',
             'image_url': 'https://example.org/manor.jpg'}
    assert osint._filter_sources([wrong, right], place) == [right]
    assert osint._filter_photos([wrong, right], place) == [right]
    report = osint._refilter_report({'items': [wrong, right], 'photos': [wrong, right],
                                   'assessment': {}}, place)
    assert wrong not in report['items']
    assert report['photos'] == []
    assert any(row['candidate']['url'] == right['url'] and row['status'] == 'unconfirmed'
               for row in report['verification']['sources'])
    assert report['assessment'] == osint.assess_osint_items(report['items'])
