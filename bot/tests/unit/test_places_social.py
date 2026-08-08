from types import SimpleNamespace
from unittest.mock import AsyncMock

from interface.handlers.places_social import report_place_missing


async def test_nonexistent_report_requires_ten_user_ratings():
    places = SimpleNamespace(
        get_user_ratings_count=AsyncMock(return_value=9),
        report_place_nonexistent=AsyncMock(),
    )
    callback = SimpleNamespace(
        data="place_missing_42",
        from_user=SimpleNamespace(id=1001),
        answer=AsyncMock(),
    )

    await report_place_missing.__wrapped__(
        callback=callback,
        state=SimpleNamespace(),
        db=SimpleNamespace(places=places),
    )

    callback.answer.assert_awaited_once_with(
        "Чтобы отметить место как несуществующее, сначала оцените 10 мест. "
        "Сейчас: 9/10",
        show_alert=True,
    )
    places.report_place_nonexistent.assert_not_awaited()


async def test_nonexistent_report_is_allowed_after_ten_user_ratings():
    places = SimpleNamespace(
        get_user_ratings_count=AsyncMock(return_value=10),
        report_place_nonexistent=AsyncMock(
            return_value={
                "added": False,
                "count": 1,
                "hidden": False,
                "not_found": False,
            }
        ),
    )
    callback = SimpleNamespace(
        data="place_missing_42",
        from_user=SimpleNamespace(id=1001),
        answer=AsyncMock(),
    )

    await report_place_missing.__wrapped__(
        callback=callback,
        state=SimpleNamespace(),
        db=SimpleNamespace(places=places),
    )

    places.report_place_nonexistent.assert_awaited_once_with(
        place_id=42,
        user_id=1001,
    )
    callback.answer.assert_awaited_once_with(
        "Вы уже отмечали это место",
        show_alert=True,
    )
