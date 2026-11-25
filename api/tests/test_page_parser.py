import json
from infrastructure.osint.osint_identity import extract_page_identity, primary_gallery
from infrastructure.osint.osint_description import _extract_generic_image_urls

URL = 'https://example.org/estate'


def test_responsive_lazy_images_and_excluded_sections():
    html = '''<main><article><h1>Усадьба</h1>
    <img src="/placeholder.gif" data-src="/estate.jpg">
    <img src="/small.jpg" srcset="/medium.jpg 400w, /large.jpg 1200w">
    <picture><source data-srcset="/wide.webp 2x, /narrow.webp 1x"></picture>
    <div id="related"><img src="/neighbour.jpg"></div>
    <aside><img src="/other.jpg"></aside>
    <img src="javascript:alert(1)"></article>
    <img src="/outside-article.jpg"></main>'''
    expected = [URL.replace('/estate', p) for p in ['/estate.jpg', '/large.jpg', '/wide.webp']]
    assert primary_gallery(html, URL) == (True, expected)
    assert _extract_generic_image_urls(html, URL) == expected


def test_microdata_place_identity_and_gallery():
    html = '''<div itemscope itemtype="https://schema.org/Place">
    <meta itemprop="name" content="Усадьба Шилля">
    <link itemprop="url" href="/estate">
    <div itemprop="address" itemscope itemtype="https://schema.org/PostalAddress">
    <meta itemprop="streetAddress" content="улица Кардовского, 33">
    <meta itemprop="addressLocality" content="Переславль-Залесский"></div>
    <div itemprop="geo" itemscope itemtype="https://schema.org/GeoCoordinates">
    <meta itemprop="latitude" content="56.72739"><meta itemprop="longitude" content="38.84294"></div>
    <link itemprop="image" href="/estate.jpg"></div>'''
    identity = extract_page_identity(html, URL)
    assert identity['title'] == 'Усадьба Шилля'
    assert identity['latitude'] == '56.72739'
    assert identity['locality'] == 'Переславль-Залесский'
    assert primary_gallery(html, URL) == (True, ['https://example.org/estate.jpg'])


def structured(node):
    return '<title>Усадьба</title><script type="application/ld+json">' + json.dumps(node) + '</script>'


def test_main_entity_does_not_use_publisher_or_recommendations():
    node = {'@type': 'WebPage', 'mainEntity': {'@type': 'Place', 'name': 'Усадьба', 'image': '/own.jpg'},
            'publisher': {'address': 'Другой город', 'image': '/logo.jpg'},
            'relatedLink': {'@type': 'Place', 'image': '/other.jpg'}}
    html = structured(node)
    assert primary_gallery(html, URL) == (True, ['https://example.org/own.jpg'])
    assert 'address' not in extract_page_identity(html, URL)


def test_foreign_entity_and_ambiguous_places_are_not_evidence():
    foreign = {'@type': 'Place', 'url': '/other', 'address': 'Другой город', 'image': '/other.jpg'}
    for html in [structured(foreign), structured({'@graph': [foreign]}),
                 structured({'@type': 'Place', 'name': 'Первое'}) + structured({'@type': 'Place', 'name': 'Второе'})]:
        assert primary_gallery(html, URL) == (False, [])
        assert 'address' not in extract_page_identity(html, URL)


def test_malformed_json_does_not_lose_article_photo():
    html = '<script type="application/ld+json">{broken</script><article><img data-src="/own.jpg"></article>'
    assert primary_gallery(html, URL) == (True, ['https://example.org/own.jpg'])


def test_nested_noise_and_protocol_relative_lazy_url():
    html = '''<article><div class="related"><div class="card"><img src="/other.jpg"></div></div>
    <img data-original="//cdn.example.org/own.jpg"></article>'''
    assert primary_gallery(html, URL) == (True, ['https://cdn.example.org/own.jpg'])


def test_generic_fetch_attaches_identity_and_scope(monkeypatch):
    from infrastructure.osint import osint_description as parser
    html = structured({'@type': 'Place', 'name': 'Усадьба', 'url': URL,
                       'image': {'@type': 'ImageObject', 'contentUrl': '/estate.jpg'}})
    monkeypatch.setattr(parser, '_fetch_generic_html', lambda url: html)
    photos = parser.generic_page_photos_for_links([{'url': URL, 'title': 'Усадьба'}])
    assert len(photos) == 1
    assert photos[0]['gallery_scope'] == 'primary'
    assert photos[0]['page_identity']['title'] == 'Усадьба'
    assert photos[0]['image_url'] == 'https://example.org/estate.jpg'
