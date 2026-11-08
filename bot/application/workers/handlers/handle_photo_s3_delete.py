"""Handle photo deletion commands from RabbitMQ."""

from typing import Any

from loguru import logger

from infrastructure.core.settings import AppSettings
from infrastructure.storage.s3 import S3Storage


async def handle_photo_s3_delete(
    message: dict[str, Any], *, settings: AppSettings,
) -> None:
    key = message.get("object_key")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("object_key must be a non-empty string.")
    await S3Storage(settings).delete_object(key)
    logger.info("S3 photo deleted: object_key={}", key)
