from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from application.place_social_service import PlaceSocialService
from application.places_view import PlacesView
from infrastructure.core.error_handler import catch_handler_errors
from infrastructure.core.event_bus import EventBus
from infrastructure.db.PgDb import AsyncDatabase
from interface.handlers.places import PAGE_SIZE, PlacesState

router = Router()


@router.callback_query(F.data.startswith("rate_"), StateFilter(PlacesState.industrial_and_abandoned_places))
@catch_handler_errors()
async def rate_place(callback: CallbackQuery, state: FSMContext, db: AsyncDatabase, event_bus: EventBus):
    _, place_id_raw, score_raw = callback.data.split("_")
    place_id = int(place_id_raw)
    score = int(score_raw)

    updated = await db.places.upsert_place_rating(
        place_id=place_id,
        user_id=callback.from_user.id,
        score=score,
    )
    if not updated:
        await callback.answer("Не удалось сохранить оценку", show_alert=True)
        return

    info = await state.get_data()
    callback_data = PlaceSocialService.normalize_back_callback_data(info.get("callback_data"))
    search = info.get("search")

    try:
        await PlacesView.edit_place_description(
            message=callback.message,
            place_id=place_id,
            callback_data=callback_data,
            db=db,
            search=search,
            user_id=callback.from_user.id,
        )
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            raise

    await event_bus.publish(
        "place.rating.changed",
        {"place_id": place_id, "user_id": callback.from_user.id, "score": score},
    )
    if score == 0:
        await callback.answer("Оценка удалена")
    else:
        await callback.answer(f"Оценка {score}/5 сохранена")


@router.callback_query(F.data.startswith("review_show_"), StateFilter(PlacesState.industrial_and_abandoned_places))
@catch_handler_errors()
async def show_place_reviews(callback: CallbackQuery, db: AsyncDatabase):
    _, _, place_id_raw, offset_raw = callback.data.split("_")
    place_id = int(place_id_raw)
    offset = max(0, int(offset_raw))
    await PlacesView.edit_reviews_page(
        message=callback.message,
        db=db,
        place_id=place_id,
        offset=offset,
        reviews_page_size=PAGE_SIZE,
        include_bulk_delete=True,
        include_single_delete=False,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("review_del_all_"), StateFilter(PlacesState.industrial_and_abandoned_places))
@catch_handler_errors()
async def delete_all_my_reviews(callback: CallbackQuery, db: AsyncDatabase, event_bus: EventBus):
    _, _, _, place_id_raw, offset_raw = callback.data.split("_")
    place_id = int(place_id_raw)
    offset = max(0, int(offset_raw))
    deleted_count = await db.places.delete_all_user_reviews(
        place_id=place_id,
        user_id=callback.from_user.id,
    )
    if deleted_count == 0:
        await callback.answer("У вас нет отзывов для удаления", show_alert=True)
        return

    await PlacesView.edit_reviews_page(
        message=callback.message,
        db=db,
        place_id=place_id,
        offset=offset,
        reviews_page_size=PAGE_SIZE,
        include_bulk_delete=True,
        include_single_delete=False,
    )
    await event_bus.publish(
        "place.review.deleted_bulk",
        {"place_id": place_id, "user_id": callback.from_user.id, "deleted_count": deleted_count},
    )
    await callback.answer(f"Удалено отзывов: {deleted_count}")


@router.callback_query(F.data.startswith("review_del_"), StateFilter(PlacesState.industrial_and_abandoned_places))
@catch_handler_errors()
async def delete_my_review(callback: CallbackQuery, db: AsyncDatabase, event_bus: EventBus):
    _, _, place_id_raw, review_id_raw, offset_raw = callback.data.split("_")
    place_id = int(place_id_raw)
    review_id = int(review_id_raw)
    offset = max(0, int(offset_raw))

    deleted = await db.places.delete_place_review(review_id=review_id, user_id=callback.from_user.id)
    if not deleted:
        await callback.answer("Можно удалить только свой отзыв", show_alert=True)
        return

    await PlacesView.edit_reviews_page(
        message=callback.message,
        db=db,
        place_id=place_id,
        offset=offset,
        reviews_page_size=PAGE_SIZE,
        user_id=callback.from_user.id,
        include_bulk_delete=False,
        include_single_delete=True,
        normalize_offset=True,
    )
    await event_bus.publish(
        "place.review.deleted",
        {"place_id": place_id, "review_id": review_id, "user_id": callback.from_user.id},
    )
    await callback.answer("Отзыв удален")


@router.callback_query(F.data.startswith("review_back_"), StateFilter(PlacesState.industrial_and_abandoned_places))
@catch_handler_errors()
async def reviews_back_to_place(callback: CallbackQuery, state: FSMContext, db: AsyncDatabase):
    place_id = int(callback.data.split("_")[2])
    info = await state.get_data()
    callback_data = PlaceSocialService.normalize_back_callback_data(info.get("callback_data"))
    search = info.get("search")
    await PlacesView.edit_place_description(
        message=callback.message,
        place_id=place_id,
        callback_data=callback_data,
        db=db,
        search=search,
        user_id=callback.from_user.id,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("photo_open_"), StateFilter(PlacesState.industrial_and_abandoned_places))
@catch_handler_errors()
async def open_place_media(callback: CallbackQuery, state: FSMContext):
    place_id = int(callback.data.split("_")[2])

    await state.update_data(
        social_place_id=place_id,
        social_message_id=callback.message.message_id,
        social_chat_id=callback.message.chat.id,
        social_prompt_message_id=None,
    )
    await state.set_state(PlacesState.awaiting_social_input)
    await callback.message.edit_reply_markup(reply_markup=PlaceSocialService.social_cancel_keyboard())
    await callback.answer("Отправьте текст отзыва или фото (можно с подписью)")


@router.callback_query(F.data.startswith("photo_show_"), StateFilter(PlacesState.industrial_and_abandoned_places))
@catch_handler_errors()
async def show_place_photos(callback: CallbackQuery, db: AsyncDatabase):
    _, _, place_id_raw, offset_raw = callback.data.split("_")
    place_id = int(place_id_raw)
    offset = max(0, int(offset_raw))
    shown = await PlacesView.show_photos_page(
        message=callback.message,
        db=db,
        place_id=place_id,
        offset=offset,
    )
    if not shown:
        await callback.answer("Пока нет фото", show_alert=True)
        return
    await callback.answer()


@router.callback_query(F.data.startswith("photo_del_all_"), StateFilter(PlacesState.industrial_and_abandoned_places))
@catch_handler_errors()
async def delete_all_my_photos(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncDatabase,
    event_bus: EventBus,
):
    _, _, _, place_id_raw, _ = callback.data.split("_")
    place_id = int(place_id_raw)
    deleted_count = await db.places.delete_all_user_photos(
        place_id=place_id,
        user_id=callback.from_user.id,
    )
    if deleted_count == 0:
        await callback.answer("У вас нет фото для удаления", show_alert=True)
        return

    info = await state.get_data()
    callback_data = PlaceSocialService.normalize_back_callback_data(info.get("callback_data"))
    search = info.get("search")
    await event_bus.publish(
        "place.photo.deleted_bulk",
        {"place_id": place_id, "user_id": callback.from_user.id, "deleted_count": deleted_count},
    )
    try:
        await PlacesView.edit_place_description(
            message=callback.message,
            place_id=place_id,
            callback_data=callback_data,
            db=db,
            search=search,
            user_id=callback.from_user.id,
        )
    except TelegramBadRequest:
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        await PlacesView.view_place_description(
            message=callback.message,
            place_id=place_id,
            callback_data=callback_data,
            db=db,
            search=search,
            user_id=callback.from_user.id,
        )
    await callback.answer(f"Удалено фото: {deleted_count}")


@router.callback_query(F.data.startswith("photo_back_"), StateFilter(PlacesState.industrial_and_abandoned_places))
@catch_handler_errors()
async def photos_back_to_place(callback: CallbackQuery, state: FSMContext, db: AsyncDatabase):
    place_id = int(callback.data.split("_")[2])
    info = await state.get_data()
    callback_data = PlaceSocialService.normalize_back_callback_data(info.get("callback_data"))
    search = info.get("search")
    try:
        await PlacesView.edit_place_description(
            message=callback.message,
            place_id=place_id,
            callback_data=callback_data,
            db=db,
            search=search,
            user_id=callback.from_user.id,
        )
    except TelegramBadRequest:
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        await PlacesView.view_place_description(
            message=callback.message,
            place_id=place_id,
            callback_data=callback_data,
            db=db,
            search=search,
            user_id=callback.from_user.id,
        )
    await callback.answer()


@router.callback_query(
    F.data == "social_cancel",
    StateFilter(PlacesState.awaiting_social_input),
)
@catch_handler_errors()
async def cancel_social_action_callback(callback: CallbackQuery, state: FSMContext, db: AsyncDatabase):
    await PlaceSocialService.finish_social_action(
        message=callback.message,
        state=state,
        db=db,
        user_id=callback.from_user.id,
        target_state=PlacesState.industrial_and_abandoned_places,
        delete_current_message=False,
    )
    await callback.answer()


@router.message(StateFilter(PlacesState.awaiting_social_input), F.text)
@catch_handler_errors()
async def save_review(message: Message, state: FSMContext, db: AsyncDatabase, event_bus: EventBus):
    info = await state.get_data()
    place_id = info.get("social_place_id")
    social_message_id = info.get("social_message_id")
    social_chat_id = info.get("social_chat_id")
    social_prompt_message_id = info.get("social_prompt_message_id")
    callback_data = PlaceSocialService.normalize_back_callback_data(info.get("callback_data"))
    search = info.get("search")
    user_name = message.from_user.username or message.from_user.full_name
    review_text = (message.text or "").strip()

    if not review_text:
        await message.answer("Отзыв не может быть пустым. Отправьте текст отзыва.")
        return

    added = await db.places.add_place_review(
        place_id=int(place_id),
        user_id=message.from_user.id,
        user_name=user_name,
        text=review_text,
    )
    await state.set_state(PlacesState.industrial_and_abandoned_places)
    if not added:
        await message.answer("Не удалось сохранить отзыв.")
        return

    if social_prompt_message_id is not None:
        await PlaceSocialService.delete_message_by_id_safely(message=message, message_id=int(social_prompt_message_id))
    await PlaceSocialService.delete_chat_message_safely(message=message)
    await event_bus.publish(
        "place.review.added",
        {"place_id": int(place_id), "user_id": message.from_user.id},
    )
    if social_message_id is not None and social_chat_id is not None:
        try:
            await PlacesView.edit_place_description_by_ids(
                bot=message.bot,
                chat_id=int(social_chat_id),
                message_id=int(social_message_id),
                place_id=place_id,
                callback_data=callback_data,
                db=db,
                search=search,
                user_id=message.from_user.id,
            )
            return
        except TelegramBadRequest as error:
            if "message is not modified" in str(error):
                return

    await PlacesView.view_place_description(
        message=message,
        place_id=place_id,
        callback_data=callback_data,
        db=db,
        search=search,
        user_id=message.from_user.id,
    )


@router.message(StateFilter(PlacesState.awaiting_social_input), F.photo)
@catch_handler_errors()
async def save_photo(message: Message, state: FSMContext, db: AsyncDatabase, event_bus: EventBus):
    info = await state.get_data()
    place_id = info.get("social_place_id")
    social_message_id = info.get("social_message_id")
    social_chat_id = info.get("social_chat_id")
    social_prompt_message_id = info.get("social_prompt_message_id")
    callback_data = PlaceSocialService.normalize_back_callback_data(info.get("callback_data"))
    search = info.get("search")
    user_name = message.from_user.username or message.from_user.full_name

    file_id = message.photo[-1].file_id
    added = await db.places.add_place_photo(
        place_id=int(place_id),
        user_id=message.from_user.id,
        user_name=user_name,
        file_id=file_id,
        caption=message.caption,
    )
    await state.set_state(PlacesState.industrial_and_abandoned_places)
    if not added:
        await message.answer("Не удалось сохранить фото.")
        return

    if social_prompt_message_id is not None:
        await PlaceSocialService.delete_message_by_id_safely(message=message, message_id=int(social_prompt_message_id))
    await PlaceSocialService.delete_chat_message_safely(message=message)
    await event_bus.publish(
        "place.photo.added",
        {"place_id": int(place_id), "user_id": message.from_user.id, "file_id": file_id},
    )

    if social_message_id is not None and social_chat_id is not None:
        try:
            await PlacesView.edit_place_description_by_ids(
                bot=message.bot,
                chat_id=int(social_chat_id),
                message_id=int(social_message_id),
                place_id=place_id,
                callback_data=callback_data,
                db=db,
                search=search,
                user_id=message.from_user.id,
            )
            return
        except TelegramBadRequest as error:
            if "message is not modified" in str(error):
                return

    await PlacesView.view_place_description(
        message=message,
        place_id=place_id,
        callback_data=callback_data,
        db=db,
        search=search,
        user_id=message.from_user.id,
    )


@router.message(StateFilter(PlacesState.awaiting_social_input))
@catch_handler_errors()
async def social_input_expected(message: Message, state: FSMContext, db: AsyncDatabase):
    await PlaceSocialService.finish_social_action(
        message=message,
        state=state,
        db=db,
        user_id=message.from_user.id,
        target_state=PlacesState.industrial_and_abandoned_places,
        delete_current_message=True,
    )
