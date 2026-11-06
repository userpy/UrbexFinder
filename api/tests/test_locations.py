from sqlalchemy import text


def test_city_resolution_and_geographic_filter(client):
    with client.app.state.engine.begin() as c:
        for name, address, lat, lon, status in [
            ('Музей', 'Советская улица, Александров, Владимирская область, 601650, Россия', 56.39, 38.72, 'published'),
            ('Усадьба', 'Садовая улица, Александров, Владимирская область, 601651, Россия', 56.40, 38.73, 'published'),
            ('Убежище', 'улица Александра Невского, Москва, Россия', 55.75, 37.62, 'published'),
            ('Скрытый', 'Александров, Другая область, Россия', 50, 40, 'pending'),
        ]:
            c.execute(text('''INSERT INTO places(name,full_address,latitude,longitude,status,category_id)
                VALUES (:name,:address,:lat,:lon,:status,1)'''), dict(name=name,address=address,lat=lat,lon=lon,status=status))
    response = client.get('/api/search/locations', params={'q':'Александров'})
    assert response.status_code == 200, response.text
    locations = response.json()['items']
    assert len(locations) == 1
    city = locations[0]
    assert city['count'] == 2
    bounds = ','.join(map(str, city['bbox']))
    params = {'locality':city['query'], 'locality_bbox':bounds, 'bbox':bounds}
    result = client.get('/api/places', params=params)
    assert result.status_code == 200, result.text
    assert {p['name'] for p in result.json()['items']} == {'Музей','Усадьба'}
    assert client.get('/api/map', params=params).json()['total'] == 2
    assert client.get('/api/search/locations', params={'q':'улица Александра Невского'}).json()['items'] == []


def test_same_named_cities_offer_separate_choices(client):
    with client.app.state.engine.begin() as c:
        c.execute(text("""INSERT INTO places(name,full_address,latitude,longitude,status,category_id) VALUES
            ('Первый','Советская улица, Мирный, Якутия, Россия',62,114,'published',1),
            ('Второй','Садовая улица, Мирный, Архангельская область, Россия',62.7,40.3,'published',1)"""))
    choices = client.get('/api/search/locations?q=Мирный').json()['items']
    assert len(choices) == 2
    assert choices[0]['label'] != choices[1]['label']
    for city in choices:
        response = client.get('/api/places', params={'locality':city['query'], 'locality_bbox':','.join(map(str,city['bbox']))})
        assert response.json()['total'] == 1


def test_prefix_suggestions_keep_distinct_cities_and_exact_selection(client):
    with client.app.state.engine.begin() as c:
        c.execute(text("""INSERT INTO places(name,full_address,latitude,longitude,status,category_id) VALUES
            ('Музей','Садовая улица, Александров, Владимирская область, Россия',56.39,38.72,'published',1),
            ('Дом','Садовая улица, Александровка, Владимирская область, Россия',56.40,38.73,'published',1),
            ('Убежище','Александровская улица, Москва, Россия',55.75,37.62,'published',1)"""))
    choices = client.get('/api/search/locations', params={'q':'Алекс'}).json()['items']
    assert {c['query'] for c in choices} == {'александров', 'александровка'}
    for city in choices:
        result = client.get('/api/places', params={'locality':city['query']}).json()
        assert result['total'] == 1
    assert client.get('/api/search/locations?q=Александров').json()['items'][0]['query'] == 'александров'
    assert client.get('/api/search/locations?q=Алекс%25').json()['items'] == []
