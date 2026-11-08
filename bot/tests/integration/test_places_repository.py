from __future__ import annotations

import pytest
from sqlalchemy import text

from infrastructure.db.PgDb import AsyncDatabase

pytestmark = pytest.mark.integration


async def _create_place(
    database: AsyncDatabase,
    *,
    name: str = "Test place",
    latitude: float = 55.751244,
    longitude: float = 37.618423,
) -> int:
    assert database.places is not None
    place_id = await database.places.add_or_update_place(
        name=name,
        description="Description",
        type_="industrial",
        latitude=latitude,
        longitude=longitude,
        category="abandoned",
    )
    assert place_id is not None
    assert await database.places.get_place_by_id(place_id) is not None
    return place_id


async def test_rating_lifecycle_recalculates_place_stats(
    database: AsyncDatabase,
):
    assert database.places is not None
    place_id = await _create_place(database)

    assert await database.places.upsert_place_rating(
        place_id,
        user_id=1001,
        score=5,
    )
    assert await database.places.upsert_place_rating(
        place_id,
        user_id=1002,
        score=1,
    )

    place = await database.places.get_place_by_id(place_id)
    assert place is not None
    assert place["rating_avg"] == 3.0
    assert place["rating_count"] == 2
    assert place["rating_score"] == 3.0
    assert await database.places.get_user_ratings_count(user_id=1001) == 1
    assert await database.places.get_user_ratings_count(user_id=1002) == 1

    assert await database.places.upsert_place_rating(
        place_id,
        user_id=1001,
        score=0,
    )
    place = await database.places.get_place_by_id(place_id)
    assert place is not None
    assert place["rating_avg"] == 1.0
    assert place["rating_count"] == 1
    assert await database.places.get_user_place_rating(
        place_id,
        user_id=1001,
    ) is None
    assert await database.places.get_user_ratings_count(user_id=1001) == 0


async def test_nonexistent_report_is_idempotent_and_can_be_cancelled(
    database: AsyncDatabase,
):
    assert database.places is not None
    place_id = await _create_place(database)

    first = await database.places.report_place_nonexistent(
        place_id,
        user_id=1001,
    )
    duplicate = await database.places.report_place_nonexistent(
        place_id,
        user_id=1001,
    )

    assert first == {
        "added": True,
        "count": 1,
        "hidden": False,
        "not_found": False,
    }
    assert duplicate == {
        "added": False,
        "count": 1,
        "hidden": False,
        "not_found": False,
    }

    result = duplicate
    for user_id in range(1002, 1011):
        result = await database.places.report_place_nonexistent(
            place_id,
            user_id=user_id,
        )

    assert result["count"] == 10
    assert result["hidden"] is True
    assert await database.places.get_place_by_id(place_id) is None

    cancelled = await database.places.cancel_place_nonexistent_report(
        place_id,
        user_id=1010,
    )
    assert cancelled["deleted"] is True
    assert cancelled["count"] == 9
    assert cancelled["hidden"] is False
    assert await database.places.get_place_by_id(place_id) is not None


async def test_reviews_and_photos_are_scoped_to_their_author(
    database: AsyncDatabase,
):
    assert database.places is not None
    place_id = await _create_place(database)

    assert await database.places.add_place_review(
        place_id,
        user_id=1001,
        text="First",
        user_name="alice",
    )
    assert await database.places.add_place_review(
        place_id,
        user_id=1002,
        text="Second",
        user_name="bob",
    )

    reviews = await database.places.get_reviews_page(place_id)
    alice_review = next(
        item for item in reviews["items"] if item["user_id"] == 1001
    )
    assert reviews["total"] == 2
    assert not await database.places.delete_place_review(
        alice_review["id"],
        user_id=1002,
    )
    assert await database.places.delete_place_review(
        alice_review["id"],
        user_id=1001,
    )
    assert await database.places.get_reviews_count(place_id) == 1

    assert await database.places.add_place_photo(
        place_id,
        user_id=1001,
        file_id="photo-1",
    )
    assert await database.places.add_place_photo(
        place_id,
        user_id=1001,
        file_id="photo-2",
    )
    assert await database.places.add_place_photo(
        place_id,
        user_id=1002,
        file_id="photo-3",
    )

    assert await database.places.get_place_photos_count(place_id) == 3
    async with database.engine.begin() as connection:
        await connection.execute(text("UPDATE place_photos SET status='published' WHERE place_id=:id"), {"id": place_id})
    deleted = await database.places.delete_all_user_photos(
        place_id,
        user_id=1001,
    )
    assert deleted == 2
    assert await database.places.get_place_photos_count(place_id) == 1
    async with database.engine.begin() as connection:
        await connection.execute(text("UPDATE places SET status='pending' WHERE id=:id"), {"id": place_id})
    assert await database.places.get_place_photos_count(place_id) == 0
    assert await database.places.get_recent_photos(place_id) == []
    assert (await database.places.get_photos_page(place_id))["items"] == []


async def test_get_places_by_ids_preserves_search_order(
    database: AsyncDatabase,
):
    assert database.places is not None
    first_id = await _create_place(
        database,
        name="First",
        latitude=55.1,
        longitude=37.1,
    )
    second_id = await _create_place(
        database,
        name="Second",
        latitude=55.2,
        longitude=37.2,
    )
    third_id = await _create_place(
        database,
        name="Third",
        latitude=55.3,
        longitude=37.3,
    )

    result = await database.places.get_places_by_ids(
        [second_id, third_id, first_id],
        limit=2,
        offset=0,
    )

    assert result["total"] == 3
    assert [item["id"] for item in result["items"]] == [
        second_id,
        third_id,
    ]


async def test_deduplication_preserves_records_with_user_data(database):
    first = await _create_place(database, name='Original')
    async with database.engine.begin() as connection:
        duplicate = await connection.scalar(text("INSERT INTO places(name,latitude,longitude,status) SELECT 'Duplicate',latitude,longitude,status FROM places WHERE id=:id RETURNING id"), {'id': first})
        await connection.execute(text("INSERT INTO place_photos(place_id,user_id,file_id) VALUES (:id,1001,'keep-photo')"), {'id': duplicate})
    assert await database.places.deduplicate_by_coordinates() == 0
    async with database.engine.connect() as connection:
        assert await connection.scalar(text('SELECT count(*) FROM places')) == 2
        assert await connection.scalar(text('SELECT file_id FROM place_photos')) == 'keep-photo'


@pytest.mark.parametrize("nearby", [False, True])
async def test_geocaching_last_across_pages_and_search(database: AsyncDatabase, nearby):
    repo = database.places
    ids = []
    for index, category in enumerate(['Разное', 'Усадьбы', ' GeoCaching ', 'Геокэшинг']):
        place_id = await _create_place(database, name=f'Place {index}', latitude=55.8 + index * .01)
        ids.append(place_id)
        async with database.engine.begin() as connection:
            await connection.execute(text('UPDATE places SET category=:category WHERE id=:id'), {'category':category,'id':place_id})
    location = {'latitude':56.1, 'longitude':37.6} if nearby else None
    expected = [ids[1], ids[0], ids[3], ids[2]]
    plain, searched = [], []
    for offset in range(4):
        plain += [p['id'] for p in await repo.get_places(limit=1, offset=offset, location=location)]
        result = await repo.get_places_by_ids(list(reversed(ids)), limit=1, offset=offset, location=location)
        assert result['total'] == 4
        searched += [p['id'] for p in result['items']]
    assert plain == expected
    assert searched == expected


async def test_csv_import_dry_run_duplicates_and_preserves_existing(database, tmp_path):
    import csv
    place = await _create_place(database, name='Редакторское название')
    path=tmp_path/'places.csv'
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['id','name','latitude','longitude','description','category','full_address','rating_avg'])
        writer.writeheader()
        writer.writerow(dict(id=999,name='Не перезаписывать',latitude=55.751244,longitude=37.618423))
        writer.writerow(dict(id=999,name='Новое место',latitude=56.1234567,longitude=38.2,description='Описание CSV',category='Усадьбы',full_address='Улица, Город',rating_avg=5))
        writer.writerow(dict(id=1000,name='Дубликат',latitude=56.1234567,longitude=38.2))
    result=await database.places.import_places_csv(path,dry_run=True)
    assert result['new']==1 and result['skipped']==2
    assert await database.places.get_places_count()==1
    result=await database.places.import_places_csv(path)
    assert result['new']==1 and result['skipped']==2
    assert (await database.places.get_place_by_id(place))['name']=='Редакторское название'
    async with database.engine.connect() as c:
        new=(await c.execute(text("SELECT * FROM places WHERE name='Новое место'"))).mappings().one()
        assert new['status']=='published'
        assert new['rating_count']==0 and new['rating_avg']==0
        assert new['full_address']=='Улица, Город'
        assert new['category_id'] is not None
        assert new['id'] != 999
    assert (await database.places.import_places_csv(path))['new']==0


async def test_csv_import_rolls_back_on_invalid_record(database,tmp_path):
    path=tmp_path/'places.csv'
    path.write_text('name;lat;lon\nКорректная;56;38\nОшибка;NaN;38\n',encoding='utf-8')
    with pytest.raises(ValueError,match='line 3'):
        await database.places.import_places_csv(path)
    async with database.engine.connect() as c:
        assert (await c.execute(text('SELECT count(*) FROM places'))).scalar()==0
