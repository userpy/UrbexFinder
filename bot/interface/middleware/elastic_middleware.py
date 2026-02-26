from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

class ElasticMiddleware(BaseMiddleware):
    def __init__(self, elastic):
        super().__init__()
        self.elastic = elastic

    async def __call__(self, handler, event: TelegramObject, data: dict):
        data["elastic"] = self.elastic  # добавляем объект БД в data
        return await handler(event, data)
    