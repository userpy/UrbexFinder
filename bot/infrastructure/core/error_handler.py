from functools import wraps
from typing import Any, Awaitable, Callable

from aiogram.types import CallbackQuery, Message

from infrastructure.core.logger_config import setup_logger

logger = setup_logger()


def log_handler_error(func_name: str, error: Exception) -> None:
    """Centralized handler error logging."""
    logger.exception(f"[HandlerError] {func_name}: {error}")


def catch_handler_errors(
    user_message: str = "Произошла ошибка. Попробуйте позже.",
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorator for aiogram handlers: logs unexpected errors and sends safe user response."""

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception as error:
                log_handler_error(
                    func_name=f"{func.__module__}.{func.__name__}",
                    error=error,
                )

                update = None
                for arg in args:
                    if isinstance(arg, (Message, CallbackQuery)):
                        update = arg
                        break

                if isinstance(update, Message):
                    await update.answer(user_message)
                elif isinstance(update, CallbackQuery):
                    if update.message:
                        await update.message.answer(user_message)
                    await update.answer("Ошибка", show_alert=False)

                return None

        return wrapper

    return decorator
