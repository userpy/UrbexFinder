import pytest
from urbex.domain.rules import DomainError
from urbex.infrastructure.geocoding import check_description_region
from urbex.infrastructure.osint_identity import verify_source


@pytest.mark.parametrize('description,region,status', [
    ('В Московской области', 'Московская область', 'matched'),
    ('Московская обл.', 'Тверская область', 'mismatch'),
    ('Тверская область', 'Москва', 'unconfirmed'),
])
def test_region_comes_from_coordinates(description, region, status):
    def reverse(lat, lon):
        assert (lat, lon) == (56.0, 37.0)
        return {'region': region}
    result = check_description_region(dict(description=description, latitude=56, longitude=37,
                                          region='Не использовать адрес карточки'), reverse)
    assert result['status'] == status


def test_unavailable_geocoder_is_not_a_mismatch():
    def reverse(*args):
        raise DomainError('Unavailable', 503)
    assert check_description_region(dict(description='Тверская область', latitude=56, longitude=37), reverse)['status'] == 'unconfirmed'


def test_explicit_urban_link_overrides_heuristics_only_for_same_object():
    place = {'name': 'Завод', 'full_address': 'Тверская область'}
    source = {'url': 'https://urban3p.ru/object42', 'title': 'Школа, Московская область'}
    assert verify_source(place, source, ['https://urban3p.com/object42/gallery']).status == 'accepted'
    assert verify_source(place, source, ['https://urban3p.com/object43']).status == 'rejected'


def test_urban_blog_mirrors_share_identity():
    source = {'url': 'https://urban3p.ru/blogs/42', 'title': 'Школа'}
    assert verify_source({'name': 'Завод'}, source, ['https://urban3p.com/blogs/42']).status == 'accepted'
