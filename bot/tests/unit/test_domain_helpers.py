from decimal import Decimal

import pytest

from domain.decimal6 import d6
from infrastructure.services.clean_html import clean_html_to_text
from infrastructure.services.pagination_new import PaginationControl


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("55.1234564", Decimal("55.123456")),
        ("55.1234565", Decimal("55.123457")),
        (12, Decimal("12.000000")),
    ],
)
def test_decimal6_normalization(value, expected):
    assert d6(value) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (None, ""),
        ("  plain text  ", "plain text"),
        ("<p>Hello <b>world</b></p>", "Hello world"),
        ("<style>bad</style><script>bad()</script><p>Safe</p>", "Safe"),
    ],
)
def test_clean_html_to_text(source, expected):
    assert clean_html_to_text(source) == expected


@pytest.mark.parametrize(
    ("offset", "line_count", "total", "is_start", "is_end"),
    [
        (0, 5, 20, True, False),
        (5, 5, 20, False, False),
        (15, 5, 20, False, True),
        (0, 5, 0, True, True),
    ],
)
async def test_pagination_state(
    offset,
    line_count,
    total,
    is_start,
    is_end,
):
    pagination = PaginationControl(
        offset=offset,
        line_count=line_count,
        resource_count=total,
    )

    assert await pagination.is_start() is is_start
    assert await pagination.is_end() is is_end
