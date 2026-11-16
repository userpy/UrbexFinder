import pytest
from urbex.infrastructure import osint


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
    assert osint._refilter_report({'photos': wrong + [right]}, place)['photos'] == [right]


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
    assert osint._refilter_report({'items': wrong + [right]}, place)['items'] == [right]


def test_summer_kindergarten_does_not_match_age_in_biography():
    place = {'name': 'Летний детский сад', 'region': 'Московская область'}
    biography = {'title': 'Ян, Василий Григорьевич — Википедия',
                 'snippet': 'Под Сталинградом погиб 21-летний Игорь. Из Москвы пришло известие.',
                 'url': 'https://ru.wikipedia.org/wiki/Writer', 'engine': 'duckduckgo'}
    kindergarten = {'title': 'Летний детский сад №1985 (Московская область)',
                    'snippet': 'Работал до 2009 года.',
                    'url': 'https://urban3p.ru/object28021', 'engine': 'duckduckgo'}
    assert osint._filter_sources([biography, kindergarten], place) == [kindergarten]
    assert osint._refilter_report({'items': [biography, kindergarten]}, place)['items'] == [kindergarten]
    photo = dict(biography, source_url=biography['url'], image_url='https://example.org/portrait.jpg')
    assert osint._filter_photos([photo], place) == []
    inflected = dict(kindergarten, title='Фото летнего детского сада №1985')
    assert osint._filter_sources([inflected], place) == [inflected]
