from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from infrastructure.core.event_bus import EventBus


class EventBusMiddleware(BaseMiddleware):
    def __init__(self, event_bus: EventBus):
        super().__init__()
        self.event_bus = event_bus

    async def __call__(self, handler, event: TelegramObject, data: dict):
        data["event_bus"] = self.event_bus
        return await handler(event, data)
