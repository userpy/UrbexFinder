import asyncio

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from application.places_view import PlacesView
from infrastructure.db.PgDb import AsyncDatabase


class PlaceSocialService:
    @staticmethod
    def social_cancel_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="↩️ Отмена действия", callback_data="social_cancel")]
            ]
        )

    @staticmethod
    def normalize_back_callback_data(raw_callback_data: str | None) -> str:
        if not raw_callback_data:
            return "num_back_0"
        try:
            offset = int(raw_callback_data.split("_")[2])
        except (IndexError, ValueError):
            return "num_back_0"
        return f"num_back_{max(0, offset)}"

    @staticmethod
    async def delete_chat_message_safely(
        message: Message, retries: int = 2, delay_seconds: float = 0.3
    ) -> None:
        for attempt in range(retries):
            try:
                await message.delete()
                return
            except TelegramBadRequest:
                if attempt < retries - 1:
                    await asyncio.sleep(delay_seconds)

    @staticmethod
    async def delete_message_by_id_safely(
        message: Message,
        message_id: int,
        retries: int = 2,
        delay_seconds: float = 0.3,
    ) -> None:
        for attempt in range(retries):
            try:
                await message.bot.delete_message(
                    chat_id=message.chat.id,
                    message_id=message_id,
                )
                return
            except TelegramBadRequest:
                if attempt < retries - 1:
                    await asyncio.sleep(delay_seconds)

    @staticmethod
    async def finish_social_action(
        *,
        message: Message,
        state: FSMContext,
        db: AsyncDatabase,
        user_id: int,
        target_state: State,
        delete_current_message: bool = True,
    ) -> None:
        info = await state.get_data()

        place_id = info.get("social_place_id")
        social_message_id = info.get("social_message_id")
        social_chat_id = info.get("social_chat_id")
        social_prompt_message_id = info.get("social_prompt_message_id")
        callback_data = PlaceSocialService.normalize_back_callback_data(info.get("callback_data"))
        search = info.get("search")

        if social_prompt_message_id is not None:
            await PlaceSocialService.delete_message_by_id_safely(
                message=message,
                message_id=int(social_prompt_message_id),
            )

        if delete_current_message:
            await PlaceSocialService.delete_chat_message_safely(message=message)

        rendered = False

        if place_id and social_message_id and social_chat_id:
            try:
                await PlacesView.edit_place_description_by_ids(
                    bot=message.bot,
                    chat_id=int(social_chat_id),
                    message_id=int(social_message_id),
                    place_id=place_id,
                    callback_data=callback_data,
                    db=db,
                    search=search,
                    user_id=user_id,
                )
                rendered = True
            except TelegramBadRequest as error:
                if "message is not modified" in str(error):
                    rendered = True

        if not rendered and place_id:
            await PlacesView.view_place_description(
                message=message,
                place_id=place_id,
                callback_data=callback_data,
                db=db,
                search=search,
                user_id=user_id,
            )

        await state.clear()
        await state.set_state(target_state)
