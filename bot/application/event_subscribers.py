from typing import Any

from infrastructure.core.event_bus import EventBus
from infrastructure.core.logger_config import setup_logger

logger = setup_logger()


def register_event_subscribers(event_bus: EventBus) -> None:
    async def log_event(payload: dict[str, Any]) -> None:
        logger.info(f"[EventBus] {payload}")

    event_names = [
        "place.rating.changed",
        "place.review.added",
        "place.review.deleted",
        "place.review.deleted_bulk",
        "place.photo.added",
        "place.photo.deleted_bulk",
        "place.nonexistent.reported",
        "place.nonexistent.report.canceled",
    ]
    for event_name in event_names:
        event_bus.subscribe(event_name, log_event)
