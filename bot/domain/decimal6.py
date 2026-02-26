from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Union

DecimalLike = Union[Decimal, int, float, str]
SIX_DECIMAL_PLACES = Decimal("0.000001")


def d6(value: DecimalLike | None) -> Decimal | None:
    """Normalize numeric value to Decimal with scale 6."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(SIX_DECIMAL_PLACES, rounding=ROUND_HALF_UP)
