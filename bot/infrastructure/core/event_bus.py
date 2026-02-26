from collections import defaultdict
from typing import Any, Awaitable, Callable, DefaultDict

from infrastructure.core.logger_config import setup_logger

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    """Simple in-process async event bus."""

    def __init__(self) -> None:
        self._handlers: DefaultDict[str, list[EventHandler]] = defaultdict(list)
        self._logger = setup_logger()

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        self._handlers[event_name].append(handler)

    async def publish(self, event_name: str, payload: dict[str, Any]) -> None:
        handlers = self._handlers.get(event_name, [])
        if not handlers:
            return

        for handler in handlers:
            try:
                await handler(payload)
            except Exception as error:
                self._logger.exception(
                    f"[EventBus] handler failed: event={event_name} payload={payload} error={error}"
                )
