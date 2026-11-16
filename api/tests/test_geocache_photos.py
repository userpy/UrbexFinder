from urbex.infrastructure import osint, osint_description as description


def test_cache_gallery_ignores_icons_and_deduplicates_full_size(monkeypatch):
    url = 'https://geocaching.su/cache/25942'
    html = '''<title>Камень и Башня :: Геокэшинг ::</title>
        <img src="/images/cross.png"><img src="/images/share/vk.png">
        <a href="/photos/areas/108904.jpg">
          <img src="/photos/areas/thumbnails/108904.jpg"></a>
        <img src="https://geocaching.su/photos/areas/thumbnails/108905.jpg">
        <img src="/photos/users/123.jpg">
        <img src="https://other.example/photos/areas/123.jpg">'''
    monkeypatch.setattr(description, '_fetch_generic_html', lambda _: html)
    photos = description.generic_page_photos_for_links([{'url': url, 'title': url}])
    assert [p['image_url'] for p in photos] == [
        'https://geocaching.su/photos/areas/108904.jpg',
        'https://geocaching.su/photos/areas/108905.jpg',
    ]
    assert all(p['engine'] == 'geocache' and p['title'].startswith('Камень и Башня') for p in photos)
    place = {'name': 'Камень и Башня', 'region': 'Московская область',
             'description': f'Источник: {url}'}
    assert osint._refilter_report({'photos': photos}, place)['photos'] == photos
    unrelated = dict(photos[0], title='Другой объект', source_url='https://geocaching.su/cache/999')
    assert osint._filter_photos([unrelated], place) == []


def test_poetic_cache_name_does_not_match_shelter_by_one_adjective():
    place = {'name': 'Забытая обитель', 'region': 'Московская область',
             'description': 'Источник: https://geocaching.su/cache/27717'}
    shelter = {'title': 'Убежище «Забытое» (Московская область) / Подземное',
               'source_url': 'https://urban3p.ru/object10008',
               'url': 'https://urban3p.ru/object10008',
               'image_url': 'https://img04.urban3p.ru/up/o/10008/photo.jpg',
               'engine': 'urban3p'}
    relevant = dict(shelter, title='Забытая обитель — Московская область',
                    source_url='https://example.org/report', url='https://example.org/report')
    gallery = dict(shelter, title='Без подписи', engine='geocache',
                   source_url='https://geocaching.su/cache/27717',
                   image_url='https://geocaching.su/photos/areas/123.jpg')
    assert osint._filter_photos([shelter, relevant, gallery], place) == [relevant, gallery]
    assert osint._filter_sources([shelter, relevant], place) == [relevant]
    assert osint._refilter_report({'photos': [shelter, gallery]}, place)['photos'] == [gallery]


def test_saved_empty_gallery_recovers_and_failed_fetch_has_cooldown(monkeypatch):
    place = {'id': 40814, 'name': 'Безымянные герои',
             'description': 'Источник: https://geocaching.su/cache/9735'}
    stored = {'items': [], 'photos': [], 'total': 0, 'photos_total': 0}
    monkeypatch.setattr(osint, 'load_osint_report', lambda *args: stored.copy())
    def save(engine, place_id, report):
        stored.update(report)
        return report
    monkeypatch.setattr(osint, 'save_osint_report', save)
    calls = []
    monkeypatch.setattr(osint, 'generic_page_photos_for_links', lambda *args, **kwargs: calls.append(1) or [])
    osint.get_or_build_osint_report(None, '', '', place)
    osint.get_or_build_osint_report(None, '', '', place)
    assert len(calls) == 1
    stored['geocache_photos_checked_at'] = 0
    photo = {'engine': 'geocache', 'title': 'Без подписи',
             'source_url': 'https://geocaching.su/cache/9735',
             'image_url': 'https://geocaching.su/photos/areas/41743.jpg'}
    monkeypatch.setattr(osint, 'generic_page_photos_for_links', lambda *args, **kwargs: [photo])
    assert osint.get_or_build_osint_report(None, '', '', place)['photos'] == [photo]
    monkeypatch.setattr(osint, 'generic_page_photos_for_links', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('Gallery already present')))
    assert osint.get_or_build_osint_report(None, '', '', place)['photos'] == [photo]
