from pathlib import Path

import pytest

from application.places_view import PlacesView
from infrastructure.services.template_renderer import TemplateRenderer


TEMPLATE_DIR = Path(__file__).parents[2] / "interface" / "handlers" / "templates"


def _render_place(nonexistent_reports_count: int) -> str:
    renderer = TemplateRenderer(template_dir=str(TEMPLATE_DIR))
    return renderer.render(
        template_name="place_view.html",
        params={
            "description": "Описание",
            "name": "Место",
            "full_address": "Адрес",
            "search": None,
            "rating_avg": 0,
            "rating_count": 0,
            "user_rating": None,
            "reviews_count": 0,
            "photos_count": 0,
            "nonexistent_reports_count": nonexistent_reports_count,
        },
    )


def test_place_card_shows_nonexistent_reports_count():
    rendered = _render_place(nonexistent_reports_count=3)

    assert "Возможно, не существует — отметок:" in rendered
    assert "3/10" in rendered


def test_place_card_hides_nonexistent_notice_without_reports():
    rendered = _render_place(nonexistent_reports_count=0)

    assert "Возможно, не существует" not in rendered


@pytest.mark.parametrize(
    ("user_ratings_count", "user_reported_nonexistent", "expected_text"),
    [
        (9, False, "Не существует 🔒 9/10"),
        (10, False, "Не существует 📡❌"),
        (0, True, "Отменить отметку"),
    ],
)
def test_nonexistent_report_button_reflects_user_access(
    user_ratings_count,
    user_reported_nonexistent,
    expected_text,
):
    keyboard = PlacesView._place_rating_keyboard(
        callback_data="num_back_0",
        place_id=42,
        reviews_count=0,
        photos_count=0,
        user_reported_nonexistent=user_reported_nonexistent,
        user_ratings_count=user_ratings_count,
    )

    assert keyboard.inline_keyboard[-2][0].text == expected_text
