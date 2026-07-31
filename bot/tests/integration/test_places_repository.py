from __future__ import annotations

import pytest

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

    deleted = await database.places.delete_all_user_photos(
        place_id,
        user_id=1001,
    )
    assert deleted == 2
    assert await database.places.get_place_photos_count(place_id) == 1


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
