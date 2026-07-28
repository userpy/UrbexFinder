"""Telegram webhook management."""

import asyncio

from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError

from infrastructure.core.logger_config import setup_logger

logger = setup_logger()


async def delete_webhook_with_retry(
    bot: Bot,
    *,
    initial_retry_delay: float = 1.0,
    max_retry_delay: float = 30.0,
) -> None:
    """Delete the webhook, retrying transient Telegram network failures."""
    retry_delay = initial_retry_delay
    while True:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            return
        except TelegramNetworkError as exc:
            logger.warning(
                "Telegram API is unavailable while deleting the webhook; "
                "retrying in {} seconds: {}",
                retry_delay,
                exc,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)
