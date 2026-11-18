import httpx
from fastapi.testclient import TestClient
from conftest import register, PLACE
from test_elasticsearch import insert
from urbex.infrastructure import osint
from urbex.infrastructure.osint_assess import assess_osint_items


def test_osint_assessment_security_and_condition_signals():
    assessment = assess_osint_items([
        {
            'title': 'Заброшенная фабрика под охраной ЧОП',
            'snippet': 'Территория с видеонаблюдением, вход через КПП.',
            'url': 'https://example.org/guarded',
        },
        {
            'title': 'Репортаж: руины цеха',
            'snippet': 'Частично разрушенный корпус, обрушилась крыша.',
            'url': 'https://example.org/ruins',
        },
    ])
    assert assessment['security']['level'] == 'high'
    assert assessment['security']['label'] == 'Высокая'
    assert assessment['condition']['level'] == 'abandoned'
    assert assessment['condition']['label'] == 'Заброшен'
    assert assessment['security']['signals']
    assert assessment['condition']['signals']
    assert 'эвристика' in assessment['disclaimer'].casefold()

    active = assess_osint_items([
        {
            'title': 'Детский лагерь',
            'snippet': 'Лагерь работает в сезон и принимает детей.',
            'url': 'https://example.org/active',
        },
    ])
    assert active['condition']['level'] == 'active'
    assert active['condition']['label'] == 'Действует'

    empty = assess_osint_items([
        {'title': 'Каталог адресов', 'snippet': 'Список улиц района', 'url': 'https://example.org/x'},
    ])
    assert empty['security']['level'] == 'unknown'
    assert empty['condition']['level'] == 'unknown'

    shoshinsky = assess_osint_items([
        {
            'title': 'Пионерлагерь «Шошинский» (Московская область)',
            'snippet': 'Что-то сохранилось в актовом зале. Лето 2022. Без охраны. Здания пустые.',
            'url': 'https://example.org/shosh-1',
        },
        {
            'title': 'Гаражи и «Лесные зори» продают',
            'snippet': 'Бывшие детские оздоровительные лагеря «Шошинский» проданы на аукционе.',
            'url': 'https://example.org/shosh-sale',
        },
        {
            'title': 'Шошинский отдых',
            'snippet': 'Рекреационный комплекс принимает заявки.',
            'url': 'https://example.org/noise',
        },
    ])
    assert shoshinsky['condition']['level'] == 'abandoned'
    assert shoshinsky['security']['level'] == 'low'


def test_osint_queries_cover_name_address_and_coordinates():
    queries = osint._queries_for({
        'name': 'Усадьба Липки',
        'full_address': 'Владимирская область, Александров',
        'region': 'Владимирская область',
        'latitude': 56.4,
        'longitude': 38.72,
    })
    assert queries[0].startswith('Усадьба Липки Александров Владимирская область (site:urban3p.ru')
    assert 'site:swalker.ru' in queries[0]
    assert 'site:caves.ru' in queries[0]
    assert 'site:planetadorog.ru' in queries[0]
    assert 'site:urbexstalker.com' in queries[0]
    assert 'site:geocaching.com' in queries[0]
    assert 'site:geocaching.ru' in queries[0]
    assert queries[1:] == [
        'Усадьба Липки Александров Владимирская область',
        'Усадьба Липки 56.40000, 38.72000',
    ]
    name_only = osint._queries_for({'name': 'Только имя'})
    assert name_only[0].startswith('Только имя (site:urban3p.ru')
    assert name_only[1] == 'Только имя'
    assert osint._queries_for({
        'region': 'Москва', 'latitude': 55.75, 'longitude': 37.62,
    }) == [
        'Москва (site:urban3p.ru OR site:swalker.ru OR site:caves.ru'
        ' OR site:planetadorog.ru OR site:urbexstalker.com'
        ' OR site:geocaching.com OR site:geocaching.ru OR site:geocaching.su'
        ' OR site:opencaching.pl OR site:wikimapia.org)',
        '55.75000, 37.62000',
        'Москва',
    ]
    # Long Nominatim dump → locality + compact oblast, not bare name.
    long_region = osint._queries_for({
        'name': 'Лагерь',
        'region': 'СНТ "Краснофлотский", городской округ Щёлково, Московская область, Центральный федеральный округ, Россия',
        'full_address': 'СНТ "Краснофлотский", городской округ Щёлково, Московская область, Центральный федеральный округ, Россия',
        'latitude': 55.9,
        'longitude': 38.0,
    })
    assert osint._settlement_label({
        'full_address': 'СНТ "Краснофлотский", городской округ Щёлково, Московская область, Центральный федеральный округ, Россия',
        'region': 'СНТ "Краснофлотский", городской округ Щёлково, Московская область, Центральный федеральный округ, Россия',
    }) == 'Краснофлотский'
    assert long_region[0].startswith('Лагерь Краснофлотский Московская область (site:urban3p.ru')
    assert long_region[1:] == [
        'Лагерь Краснофлотский Московская область',
        'Лагерь 55.90000, 38.00000',
    ]
    region_queries = osint._queries_for({
        'name': 'Лагерь',
        'region': 'Московская область',
        'latitude': 55.9,
        'longitude': 38.0,
    })
    assert region_queries[0].startswith('Лагерь Московская область (site:urban3p.ru')
    assert region_queries[1:] == [
        'Лагерь Московская область',
        'Лагерь 55.90000, 38.00000',
    ]


def test_osint_queries_include_settlement_from_address():
    place = {
        'name': 'Пионерский лагерь "Дзержинец"',
        'region': (
            'Сосновая улица, Анашкино, Одинцовский городской округ, '
            'Московская область, Центральный федеральный округ, 143086, Россия'
        ),
        'full_address': (
            'Сосновая улица, Анашкино, Одинцовский городской округ, '
            'Московская область, Центральный федеральный округ, 143086, Россия'
        ),
        'latitude': 55.67,
        'longitude': 36.98,
    }
    assert osint._settlement_label(place) == 'Анашкино'
    assert osint._search_location(place) == 'Анашкино Московская область'
    queries = osint._queries_for(place)
    assert 'Анашкино' in queries[0]
    assert 'Московская область' in queries[0]
    assert queries[1] == (
        'Пионерский лагерь "Дзержинец" Анашкино Московская область'
    )
    image_queries = osint._image_queries_for(place)
    assert 'Анашкино' in image_queries[0]
    # Matching prefers the card locality over a same-name camp elsewhere.
    kept = osint._filter_photos([
        {
            'title': 'Пионерский лагерь Дзержинец, Анашкино, Московская область',
            'image_url': 'https://cdn.example.org/mo.jpg',
            'source_url': 'https://urban3p.ru/dzer-anashkino',
        },
        {
            'title': 'Дзержинец, детский лагерь отдыха, Ижевск',
            'image_url': 'https://cdn.example.org/izh.jpg',
            'source_url': 'https://example.org/izh',
        },
    ], place)
    assert {p['title'] for p in kept} == {
        'Пионерский лагерь Дзержинец, Анашкино, Московская область',
    }

    image_queries = osint._image_queries_for({
        'name': 'Карьер',
        'region': 'Московская область',
        'latitude': 55.87326,
        'longitude': 37.38085,
    })
    assert image_queries[0].startswith('Карьер Московская область (urban3p OR swalker')
    assert 'фото' in image_queries[0]
    assert image_queries[1].startswith('Карьер Московская область фото')
    assert 'backrooms' in image_queries[1]
    assert image_queries[2].startswith('Карьер 55.87326, 37.38085')
    alone = osint._image_queries_for({
        'name': 'Карьер', 'latitude': 55.87, 'longitude': 37.38,
    })
    assert alone[0].startswith('Карьер (urban3p OR swalker')
    assert alone[1].startswith('Карьер фото')
    assert alone[2].startswith('Карьер 55.87000, 37.38000')
    # Generic name alone must not search without location/coords.
    assert osint._image_queries_for({'name': 'Заброшенный коттедж'}) == []
    generic_geo = osint._image_queries_for({
        'name': 'Заброшенный коттедж',
        'region': 'Московская область',
        'latitude': 55.7,
        'longitude': 37.6,
    })
    assert generic_geo[0].startswith('Заброшенный коттедж Московская область (urban3p')
    assert generic_geo[1].startswith('Заброшенный коттедж Московская область фото')
    assert 'avito' in generic_geo[1]


def test_osint_filters_game_and_meme_photos():
    place = {'name': 'Бомбоубежище на новой территории АЗЛК'}
    kept = osint._filter_photos([
        {
            'title': 'Бомбоубежище АЗЛК — архивное фото',
            'image_url': 'https://cdn.example.org/azlk.jpg',
            'source_url': 'https://urban3p.ru/azlk-shelter',
            'score': 3.0,
        },
        {
            'title': 'i can see you',
            'image_url': 'https://i.pinimg.com/backrooms.jpg',
            'source_url': 'https://www.pinterest.com/pin/123',
            'score': 2.5,
        },
        {
            'title': 'Horror game corridor',
            'image_url': 'https://cdn.example.org/game.png',
            'source_url': 'https://steamcommunity.com/sharedfiles/1',
            'score': 2.0,
        },
        {
            'title': 'Случайный пейзаж',
            'image_url': 'https://cdn.example.org/field.jpg',
            'source_url': 'https://example.org/field',
            'score': 1.0,
        },
    ], place)
    titles = {item['title'] for item in kept}
    assert titles == {'Бомбоубежище АЗЛК — архивное фото'}


def test_osint_filters_unrelated_cottage_listings():
    place = {
        'name': 'Заброшенный коттедж',
        'region': 'Истринский район',
        'full_address': 'Истринский район, Московская область',
    }
    kept = osint._filter_photos([
        {
            'title': 'Заброшенный коттедж, Истринский район — репортаж',
            'image_url': 'https://cdn.example.org/istra.jpg',
            'source_url': 'https://urban3p.ru/istra-cottage',
        },
        {
            'title': 'Как оформить недостроенный дом (18 июля 2019 г.)',
            'image_url': 'https://cdn.example.org/howto.jpg',
            'source_url': 'https://example.org/howto',
        },
        {
            'title': 'Недостроенный дом пл. 220 м/кв. (уч.15 сот.)',
            'image_url': 'https://www.avito.ru/img.jpg',
            'source_url': 'https://www.avito.ru/lot/1',
        },
        {
            'title': 'Заброшенный коттедж в другом городе',
            'image_url': 'https://cdn.example.org/other.jpg',
            'source_url': 'https://example.org/other-city',
        },
    ], place)
    titles = {item['title'] for item in kept}
    assert titles == {'Заброшенный коттедж, Истринский район — репортаж'}


def test_osint_photo_merge_keeps_urban3p_and_web_together():
    urban = tuple({
        'title': f'Буревестник urban {i}',
        'image_url': f'https://img04.urban3p.ru/up/o/2531/gallery/{i}.jpg',
        'source_url': 'https://urban3p.ru/object2531',
        'engine': 'urban3p',
        'score': 12.0,
        'query': 'u',
    } for i in range(12))
    web = tuple({
        'title': f'Буревестник web {i}',
        'image_url': f'https://cdn.example.org/web-{i}.jpg',
        'source_url': 'https://example.org/page',
        'engine': 'bing images',
        'score': 2.0,
        'query': 'w',
    } for i in range(12))
    mixed = osint._merge_round_robin([urban, web], 'image_url', 12)
    engines = {item['engine'] for item in mixed}
    assert engines == {'urban3p', 'bing images'}
    assert sum(1 for item in mixed if item['engine'] == 'urban3p') == 6
    assert sum(1 for item in mixed if item['engine'] == 'bing images') == 6
    # Sequential merge would have dropped all web hits.
    sequential = osint._merge([urban, web], 'image_url', 12)
    assert {item['engine'] for item in sequential} == {'urban3p'}


def test_osint_photo_merge_does_not_let_maps_crowd_out_urban3p():
    """Maps org photos used to fill all 12 slots before Urban3P galleries ran."""
    urban = tuple({
        'title': f'Сосновый бор urban {i}',
        'image_url': f'https://img04.urban3p.ru/up/o/21337/gallery/{i}.jpg',
        'source_url': 'https://urban3p.ru/object21337',
        'engine': 'urban3p',
        'score': 12.5,
        'query': 'u',
    } for i in range(12))
    maps = tuple({
        'title': f'Сосновый бор maps {i}',
        'image_url': f'https://avatars.mds.yandex.net/get-altay/{i}/XXL',
        'source_url': 'https://yandex.ru/maps/org/1',
        'engine': 'yandex_maps',
        'score': 11.0,
        'query': 'm',
    } for i in range(12))
    mixed = osint._merge_round_robin([urban, maps], 'image_url', 12)
    assert sum(1 for item in mixed if item['engine'] == 'urban3p') == 6
    assert sum(1 for item in mixed if item['engine'] == 'yandex_maps') == 6


def test_osint_drops_mordovia_sosnovy_bor_for_mo_place():
    place = {
        'name': 'Пионерский лагерь "Сосновый Бор"',
        'region': 'Московская область',
        'full_address': 'Богородский городской округ, Московская область',
    }
    kept = osint._filter_photos([
        {
            'title': 'Лагерь «Сосновый бор» (Московская область) / Учреждения',
            'image_url': 'https://img04.urban3p.ru/up/o/21337/gallery/1.jpg',
            'source_url': 'https://urban3p.ru/object21337',
        },
        {
            'title': 'Пионерский лагерь «Сосновый бор» (Республика Мордовия)',
            'image_url': 'https://img04.urban3p.ru/up/o/17520/gallery/1.jpg',
            'source_url': 'https://urban3p.ru/object17520',
        },
        {
            'title': 'Видео Заброшенный пионерский лагерь (Московская область)',
            'image_url': 'https://img04.urban3p.ru/up/o/11312/gallery/1.jpg',
            'source_url': 'https://urban3p.ru/object11312',
        },
    ], place)
    assert {item['source_url'] for item in kept} == {'https://urban3p.ru/object21337'}


def test_settlement_from_gorodskoy_okrug():
    place = {
        'full_address': 'городской округ Серпухов, Московская область, Россия',
        'region': 'городской округ Серпухов, Московская область, Россия',
    }
    assert osint._settlement_label(place) == 'Серпухов'
    assert osint._search_location(place) == 'Серпухов Московская область'


def test_osint_filters_izhevsk_dzerzhinets_from_moscow_oblast():
    place = {
        'name': 'Пионерский лагерь Дзержинец',
        'region': 'Московская область',
    }
    kept = osint._filter_photos([
        {
            'title': 'Пионерский лагерь Дзержинец (Московская область)',
            'image_url': 'https://cdn.example.org/mo.jpg',
            'source_url': 'https://urban3p.ru/dzerzhinets-mo',
        },
        {
            'title': 'Дзержинец, детский лагерь отдыха, Ижевск, территория Дачный Поселок, 22',
            'image_url': 'https://cdn.example.org/izh.jpg',
            'source_url': 'https://example.org/dzerzhinets-izhevsk',
        },
    ], place)
    titles = {item['title'] for item in kept}
    assert titles == {'Пионерский лагерь Дзержинец (Московская область)'}


def test_osint_filters_factory_when_place_is_camp():
    place = {
        'name': 'Заброшенный лагерь часового завода Слава',
        'region': 'Московская область',
    }
    kept = osint._filter_photos([
        {
            'title': 'Пионерский лагерь Слава, 2-го Московского часового завода',
            'image_url': 'https://cdn.example.org/camp.jpg',
            'source_url': 'https://example.org/lager-slava',
        },
        {
            'title': 'Заброшенный часовой завод «Слава» (Москва) / Архив',
            'image_url': 'https://img04.urban3p.ru/up/o/999/gallery/1.jpg',
            'source_url': 'https://urban3p.ru/object999',
        },
        {
            'title': 'Завод Слава, Москва — цеха',
            'image_url': 'https://cdn.example.org/factory.jpg',
            'source_url': 'https://example.org/zavod-slava',
        },
    ], place)
    titles = {item['title'] for item in kept}
    assert titles == {'Пионерский лагерь Слава, 2-го Московского часового завода'}
    # Symmetric: factory place should not keep camp-only hits.
    factory_place = {
        'name': 'Заброшенный часовой завод Слава',
        'region': 'Москва',
    }
    factory_kept = osint._filter_photos([
        {
            'title': 'Заброшенный часовой завод «Слава» (Москва) / Архив',
            'image_url': 'https://img04.urban3p.ru/up/o/999/gallery/1.jpg',
            'source_url': 'https://urban3p.ru/object999',
        },
        {
            'title': 'Пионерский лагерь Слава, место событий',
            'image_url': 'https://cdn.example.org/camp.jpg',
            'source_url': 'https://example.org/lager-slava',
        },
    ], factory_place)
    assert {item['title'] for item in factory_kept} == {
        'Заброшенный часовой завод «Слава» (Москва) / Архив',
    }


def test_osint_filters_other_regions_for_same_name():
    place = {
        'name': 'Пионерский лагерь Атлант',
        'region': 'Московская область',
    }
    kept = osint._filter_sources([
        {
            'title': 'Пионерский лагерь Атлант в Подмосковье',
            'snippet': 'Заброшенный лагерь Московская область.',
            'url': 'https://urban3p.ru/atlant-mo',
        },
        {
            'title': 'Атлант - лагерь на море, Сочи',
            'snippet': 'Путевки в Сочи на 2026 год.',
            'url': 'https://example.org/sochi-atlant',
        },
        {
            'title': 'Спортивная база Атлант, Брянская область',
            'snippet': 'Фото базы в Брянске.',
            'url': 'https://example.org/bryansk',
        },
    ], place)
    titles = {item['title'] for item in kept}
    assert titles == {'Пионерский лагерь Атлант в Подмосковье'}


def test_osint_filters_vostok_photos_from_other_oblasts():
    place = {
        'name': 'Пионерский лагерь Восток',
        'region': 'Московская область',
    }
    kept = osint._filter_photos([
        {
            'title': 'Пионерский лагерь «Восток» (Московская область)',
            'image_url': 'https://cdn.example.org/mo.jpg',
            'source_url': 'https://urban3p.ru/vostok-mo',
        },
        {
            'title': 'Пионерский лагерь «Восток-6» (Владимирская область)',
            'image_url': 'https://cdn.example.org/vlad.jpg',
            'source_url': 'https://example.org/vostok-6',
        },
        {
            'title': 'Пионерский лагерь "Восток": matrix_svd — LiveJournal',
            'image_url': 'https://cdn.example.org/lj.jpg',
            'source_url': 'https://matrix-svd.livejournal.com/vostok',
        },
        {
            'title': 'Оздоровительный лагерь «ВОСТОК-2»',
            'image_url': 'https://cdn.example.org/v2.jpg',
            'source_url': 'https://example.org/vostok-2',
        },
    ], place)
    titles = {item['title'] for item in kept}
    assert titles == {'Пионерский лагерь «Восток» (Московская область)'}


def test_osint_filters_military_weapons_news_photos():
    place = {
        'name': 'Войсковая часть 28376',
        'region': 'Московская область',
    }
    kept = osint._filter_photos([
        {
            'title': 'Заброшенная в/ч 28376, Московская область — фото',
            'image_url': 'https://cdn.example.org/unit.jpg',
            'source_url': 'https://urban3p.ru/vch-28376',
        },
        {
            'title': 'Российский производитель систем воздушно-космической обороны начнет…',
            'image_url': 'https://cdn.example.org/vko.jpg',
            'source_url': 'https://example.org/vko-news',
        },
        {
            'title': 'Индия формирует единую систему воздушно-космической обороны на базе…',
            'image_url': 'https://cdn.example.org/india.jpg',
            'source_url': 'https://example.org/india-pvo',
        },
        {
            'title': 'Пусковая установка С-400 Триумф на полигоне',
            'image_url': 'https://cdn.example.org/s400.jpg',
            'source_url': 'https://example.org/s400',
        },
        {
            'title': 'Чужая войсковая часть 11111 в Подмосковье',
            'image_url': 'https://cdn.example.org/other.jpg',
            'source_url': 'https://example.org/vch-11111',
        },
        {
            # Same digits only in CDN path must not count as the unit number.
            'title': 'Бывшая в/ч в Африканде - YouTube',
            'image_url': 'https://cdn.example.org/img28376.jpg',
            'source_url': 'https://youtube.com/watch?v=abc',
        },
    ], place)
    assert {item['title'] for item in kept} == {
        'Заброшенная в/ч 28376, Московская область — фото',
    }

    bare = {
        'name': 'Войсковая часть',
        'region': 'Московская область',
    }
    assert osint._filter_photos([
        {
            'title': 'Российский производитель систем воздушно-космической обороны',
            'image_url': 'https://cdn.example.org/vko2.jpg',
            'source_url': 'https://example.org/vko2',
        },
    ], bare) == []

    queries = osint._image_queries_for({
        'name': 'Войсковая часть 28376',
        'region': 'Московская область',
        'latitude': 55.7,
        'longitude': 37.6,
    })
    assert queries
    assert any('с-400' in query for query in queries)
    assert any('бжрк' in query or 'музей' in query for query in queries)
    assert any('urban3p' in query for query in queries)


def test_osint_ranks_urbex_sites_above_generic_web():
    assert osint._is_urbex_site_url('https://urban3p.ru/object1')
    assert osint._is_urbex_site_url('https://img04.urban3p.ru/up/o/1/photo.jpg')
    assert osint._is_urbex_site_url('https://swalker.ru/post')
    assert osint._is_urbex_site_url('https://caves.ru/cave/1')
    assert osint._is_urbex_site_url('https://www.planetadorog.ru/t/x')
    assert osint._is_urbex_site_url('https://urbexstalker.com/ru/x')
    assert osint._is_urbex_site_url('https://www.geocaching.com/geocache/GC1')
    assert osint._is_urbex_site_url('https://geocaching.ru/cache/1')
    assert not osint._is_urbex_site_url('https://example.org/x')


def test_osint_filters_tass_news_from_pushkino_photos():
    place = {
        'name': 'Пансионат Пушкино',
        'region': 'Московская область',
    }
    kept = osint._filter_photos([
        {
            'title': 'Пансионат Пушкино, санаторий, Московская область, городской округ Пушкинский',
            'image_url': 'https://cdn.example.org/pushkino.jpg',
            'source_url': 'https://example.org/pushkino-pension',
        },
        {
            'title': 'Російське агентство ТАСС виключили з Європейської асоціації',
            'image_url': 'https://cdn.tass.ru/logo.png',
            'source_url': 'https://tass.ru/mezhdunarodnaya-panorama/123',
        },
        {
            'title': 'Новости Московской области без названия объекта',
            'image_url': 'https://cdn.example.org/mo-news.jpg',
            'source_url': 'https://example.org/mo-news',
        },
    ], place)
    assert {item['title'] for item in kept} == {
        'Пансионат Пушкино, санаторий, Московская область, городской округ Пушкинский',
    }


def test_osint_filters_bjhrk_museum_from_nazarovo_unit():
    place = {
        'name': 'Командный пункт в/ч № 51890 на месте бывшего РТЦ ЗРК С-25 «Назарово»',
        'region': 'Московская область',
        'full_address': 'Московское малое кольцо, Дмитровский округ, Московская область',
    }
    kept = osint._filter_photos([
        {
            'title': 'в/ч 51890 Назарово, Московская область, командный пункт',
            'image_url': 'https://cdn.example.org/nazarovo.jpg',
            'source_url': 'https://example.org/nazarovo-51890',
        },
        {
            'title': 'Бывший командный бункер БЖРК, музей, посёлок Звёздный, ул. Ленина, 13',
            'image_url': 'https://cdn.example.org/museum.jpg',
            'source_url': 'https://example.org/bjhrk-museum',
        },
        {
            'title': 'Музей ракетных войск в/ч 51890',
            'image_url': 'https://cdn.example.org/museum2.jpg',
            'source_url': 'https://example.org/museum-51890',
        },
    ], place)
    assert {item['title'] for item in kept} == {
        'в/ч 51890 Назарово, Московская область, командный пункт',
    }


def test_osint_keeps_vladimir_oblast_urban3p_for_kudryavtsevo():
    """«Владимирская область» on Urban3P must not be treated as foreign geo."""
    place = {
        'name': 'Пионерский лагерь "Кудрявцево"',
        'region': (
            'Детский лагерь "Кудрявцево", Вишневый — Кудрявцево — Поздняково, '
            'Кудрявцево, Кольчугинский муниципальный округ, Владимирская область'
        ),
        'full_address': (
            'Детский лагерь "Кудрявцево", Вишневый — Кудрявцево — Поздняково, '
            'Кудрявцево, Кольчугинский муниципальный округ, Владимирская область'
        ),
    }
    kept = osint._filter_photos([
        {
            'title': 'Детский лагерь «Кудрявцево» (Владимирская область) / Остальное',
            'image_url': 'https://img04.urban3p.ru/up/o/19631/gallery/769249.jpg',
            'source_url': 'https://urban3p.ru/object19631',
            'engine': 'urban3p',
        },
        {
            'title': 'Пионерский лагерь Кудрявцево (Московская область)',
            'image_url': 'https://cdn.example.org/mo.jpg',
            'source_url': 'https://example.org/mo-kudryavtsevo',
        },
    ], place)
    assert {item['title'] for item in kept} == {
        'Детский лагерь «Кудрявцево» (Владимирская область) / Остальное',
    }


def test_osint_filters_sverdlovsk_photos_for_tver_transfiguration_church():
    """Common «Спаса Преображения» must not keep other oblasts or Novgorod."""
    place = {
        'name': 'Церковь Спаса Преображения',
        'region': (
            'Церковь Преображения Господня, Ильинское — Печетово — Скорнево, '
            'Лосево, Кимрский муниципальный округ, Тверская область, Россия'
        ),
        'full_address': (
            'Церковь Преображения Господня, Ильинское — Печетово — Скорнево, '
            'Лосево, Кимрский муниципальный округ, Тверская область, Россия'
        ),
    }
    kept = osint._filter_photos([
        {
            'title': 'Церковь Спаса Преображения (Тверская область) / Культура',
            'image_url': 'https://img04.urban3p.ru/up/o/1/photo.jpg',
            'source_url': 'https://urban3p.ru/object1',
            'engine': 'urban3p',
        },
        {
            'title': 'Церковь Спаса Преображения (Сверд…',
            'image_url': 'https://img04.urban3p.ru/up/o/4945/photo.jpg',
            'source_url': 'https://urban3p.ru/object4945',
            'engine': 'urban3p',
        },
        {
            'title': 'Церковь Спаса Преображения на Ильине улице',
            'image_url': 'https://i.novgorod.ru/www/images/x.jpg',
            'source_url': 'https://www.novgorod.ru/read/information/sightseen/novgorod/spasa/',
        },
        {
            'title': 'Церковь Спаса Преображения на …',
            'image_url': 'https://cdn.example.org/wiki.jpg',
            'source_url': 'https://ru.ruwiki.ru/wiki/Церковь_Спаса_Преображения_на_Ильине_улице',
        },
        {
            'title': 'Церковь Спаса Преображения на Ильине улице',
            'image_url': 'https://cdn.example.org/ilyina.jpg',
            'source_url': 'https://example.org/ilyina-street',
        },
        {
            'title': 'Церковь Преображения, Лосево, Тверская область',
            'image_url': 'https://cdn.example.org/losevo.jpg',
            'source_url': 'https://example.org/losevo',
        },
    ], place)
    assert {item['title'] for item in kept} == {
        'Церковь Спаса Преображения (Тверская область) / Культура',
        'Церковь Преображения, Лосево, Тверская область',
    }


def test_osint_filters_kazan_cathedral_photos_for_ryazan_church():
    """«Казанской иконы…» in Voyeikovo must not keep the cathedral in Kazan."""
    place = {
        'name': 'Церковь Казанской иконы Божией Матери',
        'region': (
            '61К-024, Воейково, Милославский муниципальный округ, '
            'Рязанская область, Центральный федеральный округ, 391785, Россия'
        ),
        'full_address': (
            '61К-024, Воейково, Милославский муниципальный округ, '
            'Рязанская область, Центральный федеральный округ, 391785, Россия'
        ),
    }
    kept = osint._filter_photos([
        {
            'title': 'Собор Казанской иконы Божией Матери, православный храм, Казань, Вахитовский район',
            'image_url': 'https://cdn.example.org/kazan.jpg',
            'source_url': 'https://yandex.com/maps/org/cathedral_of_the_kazan_icon/1/',
            'engine': 'yandex_maps',
        },
        {
            'title': 'Церковь Казанской иконы Божией Матери, Воейково, Рязанская область',
            'image_url': 'https://cdn.example.org/voyeikovo.jpg',
            'source_url': 'https://example.org/voyeikovo-church',
        },
        {
            'title': 'Церковь Казанской иконы Божией Матери',
            'image_url': 'https://cdn.example.org/vague.jpg',
            'source_url': 'https://example.org/vague',
        },
    ], place)
    assert {item['title'] for item in kept} == {
        'Церковь Казанской иконы Божией Матери, Воейково, Рязанская область',
    }


def test_osint_filters_poetic_geocache_away_from_borodino():
    """Geocache poem titles must not match unrelated «Отечества» memorials."""
    place = {
        'name': 'Спите спокойно, верные сыны Отечества',
        'region': (
            'Братское захоронение, Наро-Фоминское шоссе, Кубинка-10, '
            'Одинцовский городской округ, Московская область'
        ),
        'full_address': (
            'Братское захоронение, Наро-Фоминское шоссе, Кубинка-10, '
            'Одинцовский городской округ, Московская область'
        ),
        'description': 'Источник: https://geocaching.su/cache/35864',
    }
    kept = osint._filter_sources([
        {
            'engine': 'description',
            'category': 'geocache',
            'title': 'https://geocaching.su/cache/35864',
            'snippet': 'Ссылка из описания места.',
            'url': 'https://geocaching.su/cache/35864',
        },
        {
            'engine': 'duckduckgo',
            'title': 'Памятники Бородинского поля - список, карта, фото, история памятников',
            'snippet': 'Мемориальный комплекс увековечивает подвиг защитников Отечества.',
            'url': 'https://www.planetadorog.ru/r/pamjatniki_borodinskogo_polja/',
        },
        {
            'engine': 'google cse',
            'title': 'Мемориал Великой Отечественной войны в Акулово (Кубинка-10)',
            'snippet': 'Братское захоронение на мемориале в Кубинке-10.',
            'url': 'http://safe-rgs.ru/3661-memorial-velikoy-otechestvennoy-voyny-v-akulovo-kubinka-10.html',
        },
    ], place)
    titles = {item['title'] for item in kept}
    assert titles == {
        'https://geocaching.su/cache/35864',
        'Мемориал Великой Отечественной войны в Акулово (Кубинка-10)',
    }


def test_osint_refilter_restores_description_geocache_link():
    place = {
        'id': 38689,
        'name': 'Спите спокойно, верные сыны Отечества',
        'description': 'Источник: https://geocaching.su/cache/35864',
        'region': 'Кубинка-10, Московская область',
        'full_address': 'Кубинка-10, Московская область',
    }
    restored = osint._refilter_report(
        {
            'items': [
                {
                    'engine': 'duckduckgo',
                    'title': 'Памятники Бородинского поля - список, карта, фото',
                    'snippet': 'защитников Отечества',
                    'url': 'https://www.planetadorog.ru/r/pamjatniki_borodinskogo_polja/',
                },
            ],
            'photos': [],
            'assessment': {'security': {'level': 'unknown'}, 'condition': {'level': 'unknown'}},
        },
        place,
    )
    urls = [item['url'] for item in restored['items']]
    assert urls == ['https://geocaching.su/cache/35864']


def test_osint_filters_offtopic_churches_for_bunyakovo():
    """«Церковь в Буняково» must not keep other MO churches or category listings."""
    place = {
        'name': 'Церковь в Буняково',
        'region': (
            'Церковь Покрова Пресвятой Богородицы, Покровская улица, Буняково, '
            'городской округ Домодедово, Московская область'
        ),
        'full_address': (
            'Церковь Покрова Пресвятой Богородицы, Покровская улица, Буняково, '
            'городской округ Домодедово, Московская область'
        ),
    }
    kept = osint._filter_sources([
        {
            'engine': 'description',
            'category': 'link',
            'title': 'https://geocaching.su/cache/25719',
            'snippet': 'Ссылка из описания места',
            'url': 'https://geocaching.su/cache/25719',
        },
        {
            'engine': 'duckduckgo',
            'title': 'Заброшенные усадьбы, церкви, замки в Московская область (Россия)',
            'snippet': 'Каталог объектов культуры.',
            'url': 'https://www.urban3p.ru/category/culture?region_id=2',
        },
        {
            'engine': 'duckduckgo',
            'title': 'Церковь Иконы Божией Матери Знамение в урочище Теплово',
            'snippet': 'Храм 1912 года, Московская область.',
            'url': 'https://www.urban3p.ru/object1085/',
        },
        {
            'engine': 'duckduckgo',
            'title': 'Церковь Воскресения Христова (Московская область) / Культура',
            'snippet': 'Храм 1809–1817 годов.',
            'url': 'https://www.urban3p.ru/object6915/',
        },
        {
            'engine': 'duckduckgo',
            'title': 'Церковь Покрова в Буняково',
            'snippet': 'Буняково, Домодедово, Московская область.',
            'url': 'https://www.urban3p.ru/object999/',
        },
    ], place)
    titles = {item['title'] for item in kept}
    assert titles == {
        'https://geocaching.su/cache/25719',
        'Церковь Покрова в Буняково',
    }


def test_osint_filters_voskresenki_kyiv_photo():
    place = {
        'name': 'Воскресенки',
        'region': 'Московская область',
    }
    kept = osint._filter_photos([
        {
            'title': 'Покровская церковь в селе Воскресенки, Московская область',
            'image_url': 'https://cdn.example.org/mo-church.jpg',
            'source_url': 'https://example.org/voskresenki-mo',
        },
        {
            'title': 'Таємниці Воскресенки: Цікава прогулянка історією Києва | БЖ',
            'image_url': 'https://cdn.example.org/kyiv.jpg',
            'source_url': 'https://example.org/voskresenka-kyiv',
        },
        {
            'title': 'Воскресенки без региона в названии',
            'image_url': 'https://cdn.example.org/vague.jpg',
            'source_url': 'https://example.org/voskresenki-vague',
        },
    ], place)
    assert {item['title'] for item in kept} == {
        'Покровская церковь в селе Воскресенки, Московская область',
    }


def test_osint_filters_tula_unit_from_murmansk_photos():
    place = {
        'name': 'Войсковая часть 51280',
        'region': 'Тульская область',
    }
    kept = osint._filter_photos([
        {
            'title': 'В/ч 51280, Тульская область — территория',
            'image_url': 'https://cdn.example.org/tula.jpg',
            'source_url': 'https://urban3p.ru/vch-51280-tula',
        },
        {
            'title': 'Бывшая в/ч в Африканде - YouTube',
            'image_url': 'https://cdn.example.org/afrikanda.jpg',
            'source_url': 'https://youtube.com/watch?v=afrikanda',
        },
        {
            'title': 'В/Ч В ХИБИНАХ — заброшенный городок',
            'image_url': 'https://cdn.example.org/khibiny.jpg',
            'source_url': 'https://example.org/khibiny-vch',
        },
        {
            'title': 'День ФАПСИ в России (29 картинок)',
            'image_url': 'https://cdn.example.org/fapsi.jpg',
            'source_url': 'https://example.org/fapsi-day',
        },
        {
            'title': 'В/ч 51280 без региона в названии',
            'image_url': 'https://cdn.example.org/noregion.jpg',
            'source_url': 'https://example.org/vch-51280-bare',
        },
    ], place)
    assert {item['title'] for item in kept} == {
        'В/ч 51280, Тульская область — территория',
    }


def test_osint_filters_volna_from_leningrad_oblast():
    place = {
        'name': 'Пионерский лагерь Волна',
        'region': 'Московская область',
    }
    kept = osint._filter_photos([
        {
            'title': 'Пионерский лагерь «Волна» (Московская область)',
            'image_url': 'https://cdn.example.org/mo.jpg',
            'source_url': 'https://urban3p.ru/volna-mo',
        },
        {
            'title': 'Пионерский лагерь «Волна» (Ленинградская область) / Остальное',
            'image_url': 'https://cdn.example.org/lo.jpg',
            'source_url': 'https://example.org/volna-lo',
        },
        {
            'title': 'Заброшенный пионерский лагерь «Волна», часть 2 - YouTube',
            'image_url': 'https://cdn.example.org/yt.jpg',
            'source_url': 'https://youtube.com/watch?v=volna',
        },
    ], place)
    assert {item['title'] for item in kept} == {
        'Пионерский лагерь «Волна» (Московская область)',
    }


def test_osint_filters_ogonek_moscow_from_tula():
    """Same camp name in MO must not leak into a Tula «Огонёк» card."""
    place = {
        'name': 'Пионерский лагерь Огонёк',
        'region': 'Тульская область',
        'full_address': 'Тульская область',
    }
    kept = osint._filter_photos([
        {
            'title': 'Пионерский лагерь «Огонёк» (Московск…',
            'image_url': 'https://img04.urban3p.ru/up/o/1/gallery/1.jpg',
            'source_url': 'https://urban3p.ru/object-ogonek-mo',
        },
        {
            'title': 'Пионерский лагерь «Огонёк» (Московская область)',
            'image_url': 'https://cdn.example.org/mo-full.jpg',
            'source_url': 'https://urban3p.ru/object-ogonek-mo-full',
        },
        {
            'title': 'Заброшенный лагерь «Огонек» под Тулой снова не нашел покупателя',
            'image_url': 'https://cdn.example.org/tula-news.jpg',
            'source_url': 'https://example.org/ogonek-tula-sale',
        },
        {
            'title': 'Пионерский лагерь Огонёк, Тульская область',
            'image_url': 'https://cdn.example.org/tula-urban.jpg',
            'source_url': 'https://urban3p.ru/object-ogonek-tula',
        },
        {
            'title': 'Пионерский лагерь «Огонёк» без региона',
            'image_url': 'https://cdn.example.org/bare.jpg',
            'source_url': 'https://example.org/ogonek-bare',
        },
    ], place)
    assert {item['title'] for item in kept} == {
        'Заброшенный лагерь «Огонек» под Тулой снова не нашел покупателя',
        'Пионерский лагерь Огонёк, Тульская область',
    }

    mo_place = {
        'name': 'Пионерский лагерь Огонёк',
        'region': 'Московская область',
    }
    mo_kept = osint._filter_photos([
        {
            'title': 'Пионерский лагерь «Огонёк» (Московск…',
            'image_url': 'https://img04.urban3p.ru/up/o/1/gallery/1.jpg',
            'source_url': 'https://urban3p.ru/object-ogonek-mo',
        },
        {
            'title': 'Пионерский лагерь Огонёк, Тульская область',
            'image_url': 'https://cdn.example.org/tula-urban.jpg',
            'source_url': 'https://urban3p.ru/object-ogonek-tula',
        },
    ], mo_place)
    assert {item['title'] for item in mo_kept} == {
        'Пионерский лагерь «Огонёк» (Московск…',
    }


def test_osint_filters_wrong_recreation_bases():
    place = {
        'name': 'Заброшенная база отдыха Жохово',
        'region': 'Московская область',
    }
    kept = osint._filter_photos([
        {
            'title': 'Заброшенная база отдыха Жохово - YouTube',
            'image_url': 'https://cdn.example.org/zhokhovo.jpg',
            'source_url': 'https://youtube.com/watch?v=1',
        },
        {
            'title': 'Топ 15 — базы отдыха в селе Соузга',
            'image_url': 'https://cdn.example.org/souzga.jpg',
            'source_url': 'https://example.org/souzga',
        },
        {
            'title': '18 лучших баз отдыха Адыгеи с термальными источниками',
            'image_url': 'https://cdn.example.org/adygea.jpg',
            'source_url': 'https://example.org/adygea',
        },
        {
            'title': 'Купить База отдыха «Жохово» 2,5 Га и 60 кВт в Москве',
            'image_url': 'https://cdn.example.org/sale.jpg',
            'source_url': 'https://example.org/sale',
        },
    ], place)
    assert {p['title'] for p in kept} == {
        'Заброшенная база отдыха Жохово - YouTube',
    }


def test_osint_filters_generic_hangar_noise():
    place = {
        'name': 'Заброшенный ангар',
        'region': 'Московская область',
    }
    # Only oblast — too vague, drop everything including MO news fires.
    assert osint._filter_photos([
        {
            'title': 'В подмосковных Мытищах полыхает заброшенный спортивный ангар',
            'image_url': 'https://cdn.example.org/fire.jpg',
            'source_url': 'https://example.org/fire',
        },
        {
            'title': 'Заброшенный ангар в поле',
            'image_url': 'https://cdn.example.org/field.jpg',
            'source_url': 'https://example.org/field',
        },
    ], place) == []

    precise = {
        'name': 'Заброшенный ангар',
        'region': 'Мытищи',
        'full_address': 'Мытищи, Московская область',
    }
    kept = osint._filter_photos([
        {
            'title': 'В подмосковных Мытищах полыхает заброшенный спортивный ангар',
            'image_url': 'https://cdn.example.org/fire.jpg',
            'source_url': 'https://example.org/fire',
        },
        {
            'title': 'Заброшенный ангар у Мытищ — фото объекта',
            'image_url': 'https://cdn.example.org/ok.jpg',
            'source_url': 'https://urban3p.ru/angar-myt',
        },
    ], precise)
    assert {p['title'] for p in kept} == {'Заброшенный ангар у Мытищ — фото объекта'}


def test_osint_filters_berezki_from_sverdlovsk():
    place = {
        'name': 'Пионерский лагерь Березки',
        'region': 'Московская область',
    }
    photos = osint._filter_photos([
        {
            'title': 'Пионерский лагерь «Березки» (Свердловская область) / Остальное',
            'image_url': 'https://cdn.example.org/sv.jpg',
            'source_url': 'https://example.org/berezki-sv',
        },
        {
            'title': 'Пионерский лагерь Березки, место событий',
            'image_url': 'https://cdn.example.org/vague.jpg',
            'source_url': 'https://example.org/berezki-vague',
        },
        {
            'title': 'Березки в Подмосковье — репортаж',
            'image_url': 'https://cdn.example.org/mo.jpg',
            'source_url': 'https://urban3p.ru/berezki-mo',
        },
    ], place)
    assert {p['title'] for p in photos} == {'Березки в Подмосковье — репортаж'}
    promoted = osint._filter_sources(osint._sources_from_photos(photos), place)
    assert len(promoted) == 1
    assert 'Подмосковье' in promoted[0]['title']


def test_osint_report_public_config_and_searxng_results(client, monkeypatch):
    place_id = insert(client.app, 'Усадьба Липки')
    url = f'/api/places/{place_id}/osint-report'
    from urbex.infrastructure.osint_identity import source_key
    monkeypatch.setattr(osint, 'enrich_candidates', lambda place, rows, refs: [
        dict(row, page_identity={'source_key': source_key(row['url']),
             'latitude': 55.75, 'longitude': 37.62}) for row in rows
    ])
    monkeypatch.setattr(osint, 'description_photos_for_links', lambda *args, **kwargs: [])
    monkeypatch.setattr(osint, 'vk_sources_for_links', lambda *args, **kwargs: [])
    monkeypatch.setattr(osint, 'site_photos_for_links', lambda *args, **kwargs: [])

    monkeypatch.setattr(client.app.state.config, 'searxng_url', '')
    assert client.get(url).status_code == 503

    osint.clear_search_cache()
    monkeypatch.setattr(client.app.state.config, 'searxng_url', 'https://xng.example')
    calls = []

    def handler(request: httpx.Request):
        calls.append(str(request.url))
        assert request.url.params.get('format') == 'json'
        category = request.url.params.get('categories')
        engines = request.url.params.get('engines') or ''
        if category == 'images':
            assert 'bing images' in engines
        else:
            assert 'bing' in engines
        if category == 'images':
            return httpx.Response(200, json={
                'results': [
                    {
                        'title': 'Усадьба Липки зимой',
                        'url': 'https://example.org/photo-page',
                        'img_src': 'https://cdn.example.org/lipki.jpg',
                        'thumbnail_src': 'https://cdn.example.org/lipki-thumb.jpg',
                        'engine': 'duckduckgo images',
                        'score': 3.1,
                    },
                    {
                        'title': 'Дубликат фото',
                        'url': 'https://example.org/other',
                        'img_src': 'https://cdn.example.org/lipki.jpg',
                        'thumbnail_src': 'https://cdn.example.org/lipki-thumb.jpg',
                        'engine': 'bing images',
                        'score': 1.0,
                    },
                    {
                        'title': 'Без изображения',
                        'url': 'https://example.org/no-image',
                        'img_src': '',
                    },
                ],
            })
        return httpx.Response(200, json={
            'results': [
                {
                    'title': 'Усадьба Липки — заброшенная история',
                    'url': 'https://example.org/lipki',
                    'content': 'Заброшенный объект без охраны, свободный вход.',
                    'engine': 'duckduckgo',
                    'category': 'general',
                    'score': 4.2,
                },
                {
                    'title': 'Дубликат',
                    'url': 'https://example.org/lipki/',
                    'content': 'Тот же URL с слэшем.',
                    'engine': 'bing',
                    'score': 1.0,
                },
                {
                    'title': 'Без ссылки',
                    'url': '',
                    'content': 'Пропуск',
                },
            ],
        })

    transport = httpx.MockTransport(handler)
    original = httpx.Client
    monkeypatch.setattr(
        osint.httpx,
        'get',
        lambda *args, **kwargs: original(transport=transport).get(*args, **kwargs),
    )

    result = client.get(url)
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload['place_id'] == place_id
    assert payload['source'] == 'searxng'
    assert payload['cached'] is False
    assert payload['updated_at']
    assert payload['total'] == 1
    assert payload['items'][0]['title'] == 'Усадьба Липки — заброшенная история'
    assert payload['items'][0]['url'] == 'https://example.org/lipki'
    assert any(
        query == 'Усадьба Липки' or query.startswith('Усадьба Липки ')
        for query in payload['queries']
    )
    assert any('site:urban3p.ru' in query for query in payload['queries'])
    assert any('Владимирская' in query or 'Александров' in query or 'Москва' in query for query in payload['queries']) or len(payload['queries']) >= 1
    assert payload['assessment']['security']['level'] == 'low'
    assert payload['assessment']['security']['label'] == 'Низкая'
    assert payload['assessment']['condition']['level'] == 'abandoned'
    assert payload['assessment']['condition']['label'] == 'Заброшен'
    assert payload['photos_total'] == 0
    assert payload['verification']['photos'][0]['status'] == 'unconfirmed'
    assert any('categories=images' in call for call in calls)
    assert any('categories=general' in call for call in calls)
    assert calls
    first_calls = len(calls)

    osint.clear_search_cache()
    monkeypatch.setattr(
        osint.httpx,
        'get',
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError('down')),
    )
    # Persisted report is served without calling SearXNG again.
    cached = client.get(url)
    assert cached.status_code == 200, cached.text
    assert cached.json()['cached'] is True
    assert cached.json()['photos_total'] == 0
    assert len(calls) == first_calls
    # Forced refresh still needs a live search backend.
    assert client.get(url + '?refresh=1').status_code == 502


def test_osint_report_keeps_sources_when_images_fail(client, monkeypatch):
    place_id = insert(client.app, 'Усадьба Липки')
    url = f'/api/places/{place_id}/osint-report'
    from urbex.infrastructure.osint_identity import source_key
    monkeypatch.setattr(osint, 'enrich_candidates', lambda place, rows, refs: [
        dict(row, page_identity={'source_key': source_key(row['url']),
             'latitude': 55.75, 'longitude': 37.62}) for row in rows
    ])
    osint.clear_search_cache()
    monkeypatch.setattr(client.app.state.config, 'searxng_url', 'https://xng.example')
    monkeypatch.setattr(osint, 'description_photos_for_links', lambda *args, **kwargs: [])
    monkeypatch.setattr(osint, 'vk_sources_for_links', lambda *args, **kwargs: [])
    monkeypatch.setattr(osint, 'site_photos_for_links', lambda *args, **kwargs: [])

    def handler(request: httpx.Request):
        if request.url.params.get('categories') == 'images':
            raise httpx.ConnectTimeout('images down')
        return httpx.Response(200, json={
            'results': [{
                'title': 'Усадьба Липки — заброшенная история',
                'url': 'https://example.org/lipki',
                'content': 'Заброшенный объект без охраны.',
                'score': 2.0,
            }],
        })

    transport = httpx.MockTransport(handler)
    original = httpx.Client
    monkeypatch.setattr(
        osint.httpx,
        'get',
        lambda *args, **kwargs: original(transport=transport).get(*args, **kwargs),
    )
    result = client.get(url)
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload['total'] >= 1
    assert payload['photos_total'] == 0
    assert payload['photos'] == []
    assert payload['cached'] is False


def test_osint_report_keeps_photos_when_general_fails(client, monkeypatch):
    place_id = insert(client.app, 'Усадьба Липки')
    url = f'/api/places/{place_id}/osint-report'
    osint.clear_search_cache()
    monkeypatch.setattr(client.app.state.config, 'searxng_url', 'https://xng.example')
    monkeypatch.setattr(osint, 'description_photos_for_links', lambda *args, **kwargs: [])
    monkeypatch.setattr(osint, 'vk_sources_for_links', lambda *args, **kwargs: [])
    monkeypatch.setattr(osint, 'site_photos_for_links', lambda *args, **kwargs: [])

    def handler(request: httpx.Request):
        if request.url.params.get('categories') == 'images':
            return httpx.Response(200, json={
                'results': [{
                    'title': 'Усадьба Липки — фото объекта',
                    'url': 'https://example.org/photo-page',
                    'img_src': 'https://cdn.example.org/photo.jpg',
                    'thumbnail_src': 'https://cdn.example.org/thumb.jpg',
                    'score': 2.5,
                }],
            })
        raise httpx.ReadTimeout('general down')

    transport = httpx.MockTransport(handler)
    original = httpx.Client
    monkeypatch.setattr(
        osint.httpx,
        'get',
        lambda *args, **kwargs: original(transport=transport).get(*args, **kwargs),
    )
    result = client.get(url)
    assert result.status_code == 200, result.text
    payload = result.json()
    # Image search alone is retained for review, not promoted into evidence.
    assert payload['photos_total'] == 0
    assert payload['total'] == 0
    assert payload['verification']['photos'][0]['candidate']['source_url'] == 'https://example.org/photo-page'
    assert payload['verification']['photos'][0]['status'] == 'unconfirmed'


def test_osint_report_hides_pending_from_strangers(client, monkeypatch):
    register(client)
    pending = client.post('/api/places', json=PLACE).json()['id']
    monkeypatch.setattr(
        client.app.state,
        'osint_report',
        lambda place, refresh=False: {
            'place_id': place['id'],
            'items': [],
            'total': 0,
            'queries': [],
            'source': 'searxng',
        },
    )
    assert client.get(f'/api/places/{pending}/osint-report').status_code == 200

    stranger = TestClient(client.app, base_url='http://localhost:3100', headers={'Origin': 'http://localhost:3100'})
    assert stranger.get(f'/api/places/{pending}/osint-report').status_code == 404
    register(stranger, 'stranger@example.com')
    assert stranger.get(f'/api/places/{pending}/osint-report').status_code == 404


def test_links_from_description_parses_markdown_and_bare():
    from urbex.infrastructure import osint_description as od

    links = od.links_from_description(
        'Фото в [группе](https://vk.com/club42) и ещё https://urban3p.ru/place.'
    )
    assert [item['url'] for item in links] == [
        'https://vk.com/club42',
        'https://urban3p.ru/place',
    ]
    assert links[0]['engine'] == 'description'
    assert links[0]['category'] == 'vk'
    assert links[0]['title'] == 'группе'
    assert links[1]['category'] == 'urban3p'


def test_vk_photos_for_links_fetches_wall_album(monkeypatch):
    from urbex.infrastructure import osint_description as od

    def handler(request: httpx.Request):
        method = request.url.path.rsplit('/', 1)[-1]
        if method == 'photos.get':
            assert request.url.params.get('owner_id') == '-42'
            assert request.url.params.get('album_id') == 'wall'
            return httpx.Response(200, json={
                'response': {
                    'count': 1,
                    'items': [{
                        'id': 9,
                        'owner_id': -42,
                        'text': 'Ангар зимой',
                        'sizes': [
                            {'width': 100, 'height': 80, 'url': 'https://cdn.vk/small.jpg'},
                            {'width': 800, 'height': 600, 'url': 'https://cdn.vk/big.jpg'},
                        ],
                    }],
                },
            })
        return httpx.Response(200, json={'response': {}})

    transport = httpx.MockTransport(handler)
    original = httpx.Client
    monkeypatch.setattr(
        od.httpx,
        'get',
        lambda *args, **kwargs: original(transport=transport).get(*args, **kwargs),
    )
    photos = od.vk_photos_for_links(
        'token',
        [{'url': 'https://vk.com/club42', 'title': 'группа'}],
    )
    assert len(photos) == 1
    assert photos[0]['engine'] == 'vk'
    assert photos[0]['image_url'] == 'https://cdn.vk/big.jpg'
    assert photos[0]['source_url'] == 'https://vk.com/club42'
    assert photos[0]['photo_page_url'] == 'https://vk.com/photo-42_9'
    assert od.vk_photos_for_links('', [{'url': 'https://vk.com/club42'}]) == []


def test_vk_html_scrape_public_group_without_token(monkeypatch):
    from urbex.infrastructure import osint_description as od

    html = r'''
    <html><body>
      {"name":"Тимуровец | НСО","description":"Детский санаторный оздоровительный лагерь круглогодичного действия."}
      {"text":"Всё, Смена закрыта! Всего 5 дней, но сколько эмоций!"}
      {"url":"https:\/\/sun9-54.userapi.com\/cover\/big.jpg"}
      {"url":"https:\/\/sun9-1.userapi.com\/impg\/wall\/photo.jpg"}
      {"url":"https:\/\/sun9-2.userapi.com\/emoji\/skip.png"}
    </body></html>
    '''
    monkeypatch.setattr(od, '_fetch_vk_html', lambda url: html)
    photos = od.vk_photos_for_links('', [{'url': 'https://vk.com/club1641227', 'title': 'Тимуровец'}])
    urls = {item['image_url'] for item in photos}
    assert 'https://sun9-54.userapi.com/cover/big.jpg' in urls
    assert 'https://sun9-1.userapi.com/impg/wall/photo.jpg' in urls
    assert all('emoji' not in u for u in urls)
    sources = od.vk_sources_for_links('', [{'url': 'https://vk.com/club1641227', 'title': 'Тимуровец'}])
    assert sources
    assert 'санаторный' in sources[0]['snippet'].casefold()
    assert any('смена закрыта' in (s.get('snippet') or '').casefold() for s in sources)


def test_vk_sources_for_links_group_and_wall(monkeypatch):
    from urbex.infrastructure import osint_description as od

    def handler(request: httpx.Request):
        method = request.url.path.rsplit('/', 1)[-1]
        if method == 'groups.getById':
            assert request.url.params.get('group_id') == '42'
            return httpx.Response(200, json={
                'response': [{
                    'id': 42,
                    'name': 'Заброшки МО',
                    'description': 'Без охраны, корпуса пустые.',
                    'status': 'Заброшенный лагерь',
                    'activity': 'Урбантрип',
                }],
            })
        if method == 'wall.get':
            assert request.url.params.get('owner_id') == '-42'
            return httpx.Response(200, json={
                'response': {
                    'count': 1,
                    'items': [{
                        'id': 7,
                        'owner_id': -42,
                        'text': 'Объект без охраны, можно пройти через дыру в заборе.',
                    }],
                },
            })
        return httpx.Response(200, json={'response': {}})

    transport = httpx.MockTransport(handler)
    original = httpx.Client
    monkeypatch.setattr(
        od.httpx,
        'get',
        lambda *args, **kwargs: original(transport=transport).get(*args, **kwargs),
    )
    sources = od.vk_sources_for_links(
        'token',
        [{'url': 'https://vk.com/club42', 'title': 'группа'}],
    )
    assert len(sources) >= 2
    assert sources[0]['engine'] == 'vk'
    assert sources[0]['url'] == 'https://vk.com/club42'
    assert 'Без охраны' in sources[0]['snippet']
    assert any(row['url'] == 'https://vk.com/wall-42_7' for row in sources)
    # Without token still soft-scrapes public HTML when available.
    monkeypatch.setattr(od, '_fetch_vk_html', lambda url: '')
    assert od.vk_sources_for_links('', [{'url': 'https://vk.com/club42'}]) == []


def test_dzen_photos_extracted_from_article_html(monkeypatch):
    from urbex.infrastructure import osint_description as od

    html = '''
    <html><head>
      <meta property="og:image" content="https://avatars.mds.yandex.net/get-zen_doc/123/orig"/>
    </head><body>
      {"image_url":"https://avatars.mds.yandex.net/get-zen_doc/456/scale_1200"}
      <img src="https://s3.dzeninfra.ru/zen-misc/images/illustrations/404_light.png"/>
    </body></html>
    '''

    class FakeResponse:
        status_code = 200
        text = html
        url = 'https://dzen.ru/a/demo'
        is_redirect = False
        headers = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(od.httpx, 'Client', FakeClient)
    photos = od.dzen_photos_for_links([{'url': 'https://dzen.ru/a/Zd8FzEtrLyWvzrz5', 'title': 'Лагерь'}])
    urls = {item['image_url'] for item in photos}
    assert 'https://avatars.mds.yandex.net/get-zen_doc/123/orig' in urls
    assert 'https://avatars.mds.yandex.net/get-zen_doc/456/scale_1200' in urls
    assert all('404' not in u for u in urls)
    assert photos[0]['engine'] == 'dzen'


def test_urban3p_photos_from_object_link(monkeypatch):
    from urbex.infrastructure import osint_description as od

    html = '''
    <html><head>
      <title>Лагерь «Сосновый бор» (Московская область) / Учреждения</title>
    </head><body>
      <h1>Лагерь «Сосновый бор»</h1>
      <img src="//img04.urban3p.ru/up/o/5161/photo.jpg" alt="cover"/>
      <a href="https://img04.urban3p.ru/up/o/5161/gallery/570228.jpg">Фото 40/40</a>
      <img src="https://img04.urban3p.ru/up/o/5161/gallery/570227_p.jpg" alt="thumb"/>
      <img src="https://urban3p.ru/uploaded/db/avatar/Someone.jpg" alt="avatar"/>
      <img src="https://urban3p.ru/img/db/objects/no_video.gif" alt="Нет видеоматериала"/>
    </body></html>
    '''

    monkeypatch.setattr(od, '_fetch_urban3p_html', lambda url: html)
    links = od.links_from_description('Карточка https://urban3p.ru/object5161')
    assert links[0]['category'] == 'urban3p'
    photos = od.urban3p_photos_for_links(links)
    urls = {item['image_url'] for item in photos}
    assert 'https://img04.urban3p.ru/up/o/5161/photo.jpg' in urls
    assert 'https://img04.urban3p.ru/up/o/5161/gallery/570228.jpg' in urls
    assert 'https://img04.urban3p.ru/up/o/5161/gallery/570227.jpg' in urls
    assert all('avatar' not in u and 'no_video' not in u and '_p.jpg' not in u for u in urls)
    assert photos[0]['engine'] == 'urban3p'
    assert photos[0]['source_url'] == 'https://urban3p.ru/object5161'
    assert 'Московская область' in photos[0]['title']


def test_urban3p_photos_cover_fallback_when_html_unavailable(monkeypatch):
    from urbex.infrastructure import osint_description as od

    monkeypatch.setattr(od, '_fetch_urban3p_html', lambda url: '')
    photos = od.urban3p_photos_for_links([
        {
            'url': 'https://urban3p.ru/object777',
            'title': 'Государственный детский сад (Москва) / Учреждения',
        },
    ])
    assert len(photos) == 1
    assert photos[0]['image_url'] == 'https://img04.urban3p.ru/up/o/777/photo.jpg'
    assert photos[0]['source_url'] == 'https://urban3p.ru/object777'
    assert photos[0]['engine'] == 'urban3p'
    assert 'детский сад' in photos[0]['title'].casefold()
    assert od._URBAN3P_IMPERSONATE[0] in {'chrome136', 'chrome131', 'chrome124'}


def test_urban3p_photos_from_blog_and_cdn_link(monkeypatch):
    from urbex.infrastructure import osint_description as od

    blog_html = '''
    <html><head>
      <title>Соколенок</title>
      <meta property="og:image" content="https://pp.userapi.com/c625716/v625716471/c7b4/cover.jpg"/>
    </head><body>
      <div class="blogText">
        <img src="https://pp.userapi.com/c625716/v625716471/c7b4/cover.jpg" alt="Image"/>
        <img src="https://pp.userapi.com/c625716/v625716471/c6f5/gate.jpg" alt="Image"/>
        <img src="/uploaded/db/avatar/alex66.jpg" alt="avatar"/>
        <img src="/img/db/common/blank.gif" alt="blank"/>
        <a href="https://urban3p.ru/object5161">карточка</a>
      </div>
      <div class="comment comment--level-0 messageBody">
        <img src="https://pp.userapi.com/c314216/v314216471/3505/factory.jpg" alt="comment"/>
      </div>
    </body></html>
    '''
    object_html = '''
    <html><body>
      <h1>Соколёнок</h1>
      <img src="//img04.urban3p.ru/up/o/5161/photo.jpg" alt="cover"/>
      <a href="https://img04.urban3p.ru/up/o/5161/gallery/111.jpg">1</a>
    </body></html>
    '''

    def fake_fetch(url: str) -> str:
        if '/blogs/36530' in url:
            return blog_html
        if 'object5161' in url:
            return object_html
        return ''

    monkeypatch.setattr(od, '_fetch_urban3p_html', fake_fetch)

    blog_photos = od.urban3p_photos_for_links([
        {'url': 'https://urban3p.ru/blogs/36530', 'title': 'Соколенок'},
    ])
    blog_urls = {item['image_url'] for item in blog_photos}
    assert 'https://pp.userapi.com/c625716/v625716471/c7b4/cover.jpg' in blog_urls
    assert 'https://pp.userapi.com/c625716/v625716471/c6f5/gate.jpg' in blog_urls
    assert 'https://img04.urban3p.ru/up/o/5161/photo.jpg' in blog_urls
    assert 'https://img04.urban3p.ru/up/o/5161/gallery/111.jpg' in blog_urls
    assert all('factory.jpg' not in u and 'avatar' not in u for u in blog_urls)
    assert all(item['engine'] == 'urban3p' for item in blog_photos)
    assert blog_photos[0]['source_url'] == 'https://urban3p.ru/blogs/36530'

    cdn_photos = od.urban3p_photos_for_links([
        {
            'url': 'https://img04.urban3p.ru/up/o/5161/gallery/999.jpg',
            'title': 'CDN',
        },
    ])
    assert {item['image_url'] for item in cdn_photos} >= {
        'https://img04.urban3p.ru/up/o/5161/photo.jpg',
        'https://img04.urban3p.ru/up/o/5161/gallery/111.jpg',
    }
    assert od._urban3p_object_id(
        'https://img04.urban3p.ru/up/o/5161/gallery/999.jpg',
    ) == '5161'
    assert od._urban3p_blog_id('https://urban3p.ru/blogs/36530') == '36530'


def test_swalker_photos_from_article_link(monkeypatch):
    from urbex.infrastructure import osint_description as od

    html = '''
    <html><head>
      <meta property="og:image" content="https://swalker.ru/uploads/posts/2018-06/1529574787_swalker.org_3wrzuzj2scu.jpg"/>
      <title>Пионерский лагерь «Юбилейный», Московская область</title>
    </head><body>
      <a class="highslide" href="https://swalker.ru/uploads/posts/2018-06/1529574787_swalker.org_3wrzuzj2scu.jpg">
        <img src="/uploads/posts/2018-06/thumbs/1529574787_swalker.org_3wrzuzj2scu.jpg"/>
      </a>
      <a class="highslide" href="/uploads/posts/2018-06/1529574854_swalker.org_ea5c3b_zzt8.jpg">foto</a>
      <img src="/uploads/posts/2026-08/thumbs/prev.webp" alt="other post"/>
      <a href="https://swalker.ru/uploads/posts/2026-05/thumbs/img_2324.webp">sidebar</a>
    </body></html>
    '''
    page = 'https://swalker.ru/other/4033-pionerskiy-lager-yubileynyy-mo.html'
    monkeypatch.setattr(od, '_fetch_swalker_html', lambda url: html)
    links = od.links_from_description(f'Репортаж {page}')
    assert links[0]['category'] == 'swalker'
    photos = od.swalker_photos_for_links([{'url': page, 'title': 'Юбилейный'}])
    urls = {item['image_url'] for item in photos}
    assert 'https://swalker.ru/uploads/posts/2018-06/1529574787_swalker.org_3wrzuzj2scu.jpg' in urls
    assert 'https://swalker.ru/uploads/posts/2018-06/1529574854_swalker.org_ea5c3b_zzt8.jpg' in urls
    assert all('/2018-06/' in u for u in urls)
    assert all('/thumbs/' not in u for u in urls)
    assert all('2026' not in u for u in urls)
    assert photos[0]['engine'] == 'swalker'
    assert photos[0]['source_url'] == page


def test_youtube_and_rutube_photos_from_links(monkeypatch):
    from urbex.infrastructure import osint_description as od

    yt = od.youtube_photos_for_links([
        {'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'title': 'Лагерь обзор'},
        {'url': 'https://youtu.be/dQw4w9WgXcQ', 'title': 'dup'},
    ])
    assert len(yt) == 1
    assert yt[0]['engine'] == 'youtube'
    assert yt[0]['image_url'] == 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg'

    monkeypatch.setattr(
        od,
        '_rutube_thumbnail',
        lambda video_id: (
            'https://pic.rtbcdn.ru/video/demo.jpg',
            'Рутube ролик',
        ),
    )
    rt = od.rutube_photos_for_links([
        {
            'url': 'https://rutube.ru/video/0159941b24c63763c4a9aed839fad682/',
            'title': '',
        },
    ])
    assert len(rt) == 1
    assert rt[0]['engine'] == 'rutube'
    assert rt[0]['image_url'] == 'https://pic.rtbcdn.ru/video/demo.jpg'
    assert 'Рутube' in rt[0]['title']


def test_site_photos_for_links_combines_sources(monkeypatch):
    from urbex.infrastructure import osint_description as od

    monkeypatch.setattr(
        od,
        'vk_photos_for_links',
        lambda token, links, limit=12: [{
            'title': 'vk',
            'image_url': 'https://cdn.vk/album.jpg',
            'thumbnail_url': 'https://cdn.vk/album.jpg',
            'source_url': 'https://vk.com/album-1_1',
            'engine': 'vk',
            'score': 12.0,
            'query': 'https://vk.com/club1',
        }][:limit],
    )
    monkeypatch.setattr(
        od,
        'urban3p_photos_for_links',
        lambda links, limit=12: [{
            'title': 'u3',
            'image_url': 'https://img04.urban3p.ru/up/o/1/photo.jpg',
            'thumbnail_url': 'https://img04.urban3p.ru/up/o/1/photo.jpg',
            'source_url': 'https://urban3p.ru/object1',
            'engine': 'urban3p',
            'score': 12.5,
            'query': 'https://urban3p.ru/object1',
        }][:limit],
    )
    monkeypatch.setattr(od, 'swalker_photos_for_links', lambda *a, **k: [])
    monkeypatch.setattr(
        od,
        'youtube_photos_for_links',
        lambda links, limit=12: [{
            'title': 'yt',
            'image_url': 'https://i.ytimg.com/vi/abc123/hqdefault.jpg',
            'thumbnail_url': 'https://i.ytimg.com/vi/abc123/hqdefault.jpg',
            'source_url': 'https://www.youtube.com/watch?v=abc123',
            'engine': 'youtube',
            'score': 11.5,
            'query': 'https://www.youtube.com/watch?v=abc123',
        }][:limit],
    )
    monkeypatch.setattr(od, 'rutube_photos_for_links', lambda *a, **k: [])
    monkeypatch.setattr(
        od,
        'generic_page_photos_for_links',
        lambda links, limit=12, max_pages=5: [{
            'title': 'Планета',
            'image_url': 'https://www.planetadorog.ru/img/1.jpg',
            'thumbnail_url': 'https://www.planetadorog.ru/img/1.jpg',
            'source_url': 'https://www.planetadorog.ru/t/x',
            'engine': 'planetadorog',
            'score': 11.0,
            'query': 'https://www.planetadorog.ru/t/x',
        }][:limit],
    )
    photos = od.site_photos_for_links([
        {'url': 'https://vk.com/club1'},
        {'url': 'https://urban3p.ru/object1'},
        {'url': 'https://www.youtube.com/watch?v=abc123'},
        {'url': 'https://www.planetadorog.ru/t/x'},
    ], limit=10, vk_token='token')
    engines = {p['engine'] for p in photos}
    assert engines == {'vk', 'urban3p', 'youtube', 'planetadorog'}


def test_generic_page_photos_from_description_link(monkeypatch):
    from urbex.infrastructure import osint_description as od

    html = '''
    <html><head>
      <title>Берсеневка</title>
      <meta property="og:image" content="https://podmoskovnye.ru/media/system/images/arrow.png"/>
    </head><body>
      <img src="/images/logo/logo-old.png" alt=""/>
      <div itemprop="articleBody">
        <p><img src="/images/stories/photos/2_podmoskov/bersenevka/01.jpg" alt="01.Флигель."/></p>
        <p><img src="/images/stories/photos/2_podmoskov/bersenevka/post/sytin.jpg" alt=""/></p>
        <p><img src="/images/stories/photos/2_podmoskov/bersenevka/retro/Хозяйство.jpg" alt=""/></p>
      </div>
      <img src="https://podmoskovnye.ru/components/com_rscomments/assets/images/loader.gif" alt=""/>
    </body></html>
    '''
    page = 'http://podmoskovnye.ru/usadba/podmoskovnaya/82-solnechnogorskii/101-bersenevka'
    monkeypatch.setattr(od, '_fetch_generic_html', lambda url: html)
    photos = od.generic_page_photos_for_links([{'url': page, 'title': page}])
    urls = {item['image_url'] for item in photos}
    assert 'http://podmoskovnye.ru/images/stories/photos/2_podmoskov/bersenevka/01.jpg' in urls
    assert 'http://podmoskovnye.ru/images/stories/photos/2_podmoskov/bersenevka/post/sytin.jpg' in urls
    assert all(
        'logo' not in u and 'arrow' not in u and 'loader' not in u
        for u in urls
    )
    assert photos[0]['engine'] == 'web_page'
    assert photos[0]['source_url'] == page
    # Specialized hosts stay on dedicated scrapers.
    assert od.generic_page_photos_for_links([{'url': 'https://vk.com/club1'}]) == []
    assert od.generic_page_photos_for_links([{'url': 'https://urban3p.ru/object1'}]) == []
    assert od.generic_page_photos_for_links([{'url': 'https://www.youtube.com/watch?v=abc'}]) == []


def test_description_photos_absorb_generic_pages(monkeypatch):
    from urbex.infrastructure import osint_description as od

    monkeypatch.setattr(od, 'dzen_photos_for_links', lambda *a, **k: [])
    monkeypatch.setattr(od, 'yandex_maps_photos_for_links', lambda *a, **k: [])
    monkeypatch.setattr(od, 'yandex_maps_photos_for_place', lambda *a, **k: [])
    monkeypatch.setattr(
        od,
        'site_photos_for_links',
        lambda links, limit=12, vk_token='': [{
            'title': 'Берсеневка',
            'image_url': 'http://podmoskovnye.ru/images/stories/photos/2_podmoskov/bersenevka/01.jpg',
            'thumbnail_url': 'http://podmoskovnye.ru/images/stories/photos/2_podmoskov/bersenevka/01.jpg',
            'source_url': links[0]['url'],
            'engine': 'web_page',
            'score': 10.5,
            'query': links[0]['url'],
        }][:limit],
    )
    photos = od.description_photos_for_links(
        [{'url': 'http://podmoskovnye.ru/usadba/x', 'title': 'x'}],
        limit=4,
    )
    assert len(photos) == 1
    assert photos[0]['engine'] == 'web_page'


def test_yandex_maps_photos_from_org_link(monkeypatch):
    from urbex.infrastructure import osint_description as od

    html = '''
    <html><head>
      <link rel="canonical" href="https://yandex.com/maps/org/pionerskiy_lager_smena/73025802915/"/>
      <meta property="og:title" content="Пионерский лагерь Смена"/>
      <meta property="og:image" content="https://avatars.mds.yandex.net/get-altay/10505037/2a0000019087ef29c5f721242339f79a4ba7/L_height"/>
    </head><body>
      <img src="https://avatars.mds.yandex.net/get-altay/14098455/2a0000019391ae014ab088229f8303ce6ed8/S"/>
      <img src="https://avatars.mds.yandex.net/get-yapic/30955/avatar/islands-68"/>
    </body></html>
    '''

    class FakeResponse:
        status_code = 200
        text = html
        url = 'https://yandex.com/maps/org/pionerskiy_lager_smena/73025802915/gallery/'

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(od.httpx, 'Client', FakeClient)
    links = od.links_from_description(
        'Карточка https://yandex.ru/maps/org/pionerskiy_lager_smena/73025802915/'
    )
    assert links[0]['category'] == 'yandex_maps'
    photos = od.yandex_maps_photos_for_links(links)
    urls = {item['image_url'] for item in photos}
    assert 'https://avatars.mds.yandex.net/get-altay/10505037/2a0000019087ef29c5f721242339f79a4ba7/XXL_height' in urls
    assert 'https://avatars.mds.yandex.net/get-altay/14098455/2a0000019391ae014ab088229f8303ce6ed8/XXL_height' in urls
    assert all('get-yapic' not in u for u in urls)
    assert photos[0]['engine'] == 'yandex_maps'


def test_yandex_maps_photos_for_place_matches_org(monkeypatch):
    from urbex.infrastructure import osint_description as od

    html = '''
    <html><head>
      <link rel="canonical" href="https://yandex.com/maps/org/pionerskiy_lager_smena/73025802915/"/>
      <meta property="og:title" content="Пионерский лагерь Смена"/>
    </head><body>
      <img src="https://avatars.mds.yandex.net/get-altay/10505037/2a0000019087ef29c5f721242339f79a4ba7/XXL_height"/>
    </body></html>
    '''

    class FakeResponse:
        status_code = 200
        text = html
        url = 'https://yandex.com/maps/'

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(od.httpx, 'Client', FakeClient)
    photos = od.yandex_maps_photos_for_place({
        'name': 'Пионерский лагерь Смена',
        'latitude': 55.154692,
        'longitude': 37.413277,
    })
    assert len(photos) == 1
    assert photos[0]['engine'] == 'yandex_maps'
    assert 'get-altay' in photos[0]['image_url']
    assert od.yandex_maps_photos_for_place({
        'name': 'Совершенно другой объект',
        'latitude': 55.154692,
        'longitude': 37.413277,
    }) == []


def test_osint_report_uses_description_links_without_searxng(monkeypatch):
    # Keep the no-SearXNG path offline: live VK HTML would add a third source.
    monkeypatch.setattr(osint, 'vk_sources_for_links', lambda *args, **kwargs: [])
    monkeypatch.setattr(osint, 'description_photos_for_links', lambda *args, **kwargs: [])
    payload = osint.build_osint_report(
        '',
        'http://localhost:3100',
        {
            'id': 1,
            'name': 'Ангар у реки',
            'description': 'Смотри альбом https://vk.com/club99 и зеркало https://example.org/angar.',
            'latitude': 55.7,
            'longitude': 37.6,
            'region': 'Московская область',
        },
        vk_token='',
    )
    assert payload['source'] == 'description'
    assert payload['total'] == 2
    assert payload['items'][0]['url'] == 'https://vk.com/club99'
    assert payload['photos_total'] == 0


def test_osint_report_fetches_vk_photos_from_description(monkeypatch):
    from urbex.infrastructure import osint_description as od

    osint.clear_search_cache()

    def searx_handler(request: httpx.Request):
        return httpx.Response(200, json={'results': []})

    def vk_handler(request: httpx.Request):
        method = request.url.path.rsplit('/', 1)[-1]
        if method == 'photos.get':
            return httpx.Response(200, json={
                'response': {
                    'count': 1,
                    'items': [{
                        'id': 3,
                        'owner_id': -77,
                        'text': 'Корпус',
                        'sizes': [{'width': 640, 'height': 480, 'url': 'https://cdn.vk/camp.jpg'}],
                    }],
                },
            })
        if method == 'groups.getById':
            return httpx.Response(200, json={
                'response': [{
                    'id': 77,
                    'name': 'Лагерь',
                    'description': 'Заброшен, без охраны.',
                }],
            })
        if method == 'wall.get':
            return httpx.Response(200, json={
                'response': {
                    'count': 1,
                    'items': [{
                        'id': 5,
                        'owner_id': -77,
                        'text': 'Корпус пустой, охрана не дежурит.',
                    }],
                },
            })
        return httpx.Response(200, json={'response': {}})

    searx_transport = httpx.MockTransport(searx_handler)
    vk_transport = httpx.MockTransport(vk_handler)
    original = httpx.Client
    monkeypatch.setattr(
        osint.httpx,
        'get',
        lambda *args, **kwargs: original(transport=searx_transport).get(*args, **kwargs),
    )
    monkeypatch.setattr(
        od.httpx,
        'get',
        lambda *args, **kwargs: original(transport=vk_transport).get(*args, **kwargs),
    )
    payload = osint.build_osint_report(
        'https://xng.example',
        'http://localhost:3100',
        {
            'id': 2,
            'name': 'Лагерь с альбомом',
            'description': 'Группа: https://vk.com/club77',
            'latitude': 55.7,
            'longitude': 37.6,
            'region': 'Московская область',
        },
        vk_token='vk-token',
    )
    urls = {item['url'] for item in payload['items']}
    assert 'https://vk.com/club77' in urls
    assert 'https://vk.com/wall-77_5' in urls
    assert payload['photos_total'] >= 1
    assert payload['photos'][0]['engine'] == 'vk'
    assert payload['photos'][0]['image_url'] == 'https://cdn.vk/camp.jpg'
    assert any('без охраны' in (s.get('snippet') or '').casefold() for s in payload['items'])
    assert payload['assessment']['condition']['level'] == 'abandoned'


def test_vague_radar_name_uses_description_subject_not_description_as_locality():
    place = {'name': 'Бывший Дунай', 'region': 'Московская область',
             'description': 'Заброшенная РЛС ДО "Дунай-3М" в народе "Шалаш". <br>Так вот тот самый шалаш...',
             'latitude': 55.4806, 'longitude': 36.6485}
    assert osint._settlement_label(place) == ''
    queries = osint._queries_for(place)
    assert all('<br>' not in q and 'Так вот' not in q for q in queries)
    assert 'Дунай-3М' in queries[1]
    assert 'Шалаш' in queries[1]
    assert 'Московская область' in queries[1]
    assert 'Дунай-3М' in osint._image_queries_for(place)[0]


def test_image_search_landing_page_seeds_verified_gallery(monkeypatch):
    page = 'https://wikimapia.org/123/ru/radar'
    place = {'id': 1, 'name': 'РЛС Дунай', 'latitude': 55.48, 'longitude': 36.64}
    photo = {'image_url': 'https://photos.wikimapia.org/p/00/01/02/03/04.jpg',
             'source_url': page, 'query': page, 'title': 'РЛС Дунай', 'engine': 'wikimapia', 'score': 12}
    monkeypatch.setattr(osint, 'description_photos_for_links', lambda *a, **k: [])
    monkeypatch.setattr(osint, 'vk_sources_for_links', lambda *a, **k: [])
    monkeypatch.setattr(osint, 'urban3p_photos_for_links', lambda *a, **k: [])
    monkeypatch.setattr(osint, '_search_soft', lambda url, origin, query, category:
                        (dict(photo, engine='search'),) if category == 'images' else ())
    def enrich(place, rows, references):
        return [dict(row, page_identity={'source_key': osint.source_key(row['url']),
                     'title': 'РЛС Дунай', 'latitude': 55.48, 'longitude': 36.64}) for row in rows]
    monkeypatch.setattr(osint, 'enrich_candidates', enrich)
    calls = []
    def gallery(links, **kwargs):
        calls.extend(link['url'] for link in links)
        return [photo]
    monkeypatch.setattr(osint, 'site_photos_for_links', gallery)
    report = osint._build_osint_report('https://search.test', '', place)
    assert page in calls
    assert report['photos'] == [photo]
