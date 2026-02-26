import html

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.types import InputMediaPhoto
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardButton, InlineKeyboardMarkup

from infrastructure.db.EasticSearch import ElasticPlacesIndexer
from infrastructure.db.PgDb import AsyncDatabase
from infrastructure.services.clean_html import clean_html_to_text
from infrastructure.services.pagination_new import PaginationControl
from infrastructure.services.template_renderer import TemplateRenderer


class PlacesView:
    @staticmethod
    async def __get_keyboard(buttons, page_state, start_line):
        if await page_state.is_start():
            control_buttons = [
                [
                    InlineKeyboardButton(text="Вперёд", callback_data=f"num_incr_{start_line}"),
                ],
            ]
        elif await page_state.is_end():
            control_buttons = [
                [
                    InlineKeyboardButton(text="Назад", callback_data=f"num_decr_{start_line}"),
                ],
            ]
        else:
            control_buttons = [
                [
                    InlineKeyboardButton(text="Назад", callback_data=f"num_decr_{start_line}"),
                    InlineKeyboardButton(text="Вперёд", callback_data=f"num_incr_{start_line}"),
                ],
            ]
        buttons.extend(control_buttons)
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        return keyboard

    @staticmethod
    def __render_list_places(answers, message_answer, search=None):
        params = {"search": search, "message_answer": message_answer, "places": answers}
        renderer = TemplateRenderer()
        rendered_html = renderer.render(template_name="places_message.html", params=params)
        return rendered_html

    @staticmethod
    def __render_list_place_view(
        description,
        name,
        full_address,
        search,
        rating_avg: float,
        rating_count: int,
        user_rating: int | None,
        reviews_count: int,
        photos_count: int,
    ):
        params = {
            "description": description,
            "name": name,
            "full_address": full_address,
            "search": search,
            "rating_avg": rating_avg,
            "rating_count": rating_count,
            "user_rating": user_rating,
            "reviews_count": reviews_count,
            "photos_count": photos_count,
        }
        renderer = TemplateRenderer()
        rendered_html = renderer.render(template_name="place_view.html", params=params)
        return rendered_html

    @staticmethod
    def _place_rating_keyboard(
        callback_data: str,
        place_id: int,
        reviews_count: int,
        photos_count: int,
    ) -> InlineKeyboardMarkup:
        review_row = []
        if reviews_count > 0:
            review_row.append(InlineKeyboardButton(text="💬 Отзывы", callback_data=f"review_show_{place_id}_0"))

        photo_row = [InlineKeyboardButton(text="➕ Отзыв/Фото", callback_data=f"photo_open_{place_id}")]
        if photos_count > 0:
            photo_row.append(InlineKeyboardButton(text="🖼 Фото", callback_data=f"photo_show_{place_id}_0"))

        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="0", callback_data=f"rate_{place_id}_0"),
                    InlineKeyboardButton(text="⭐ 1", callback_data=f"rate_{place_id}_1"),
                    InlineKeyboardButton(text="⭐ 2", callback_data=f"rate_{place_id}_2"),
                    InlineKeyboardButton(text="⭐ 3", callback_data=f"rate_{place_id}_3"),
                    InlineKeyboardButton(text="⭐ 4", callback_data=f"rate_{place_id}_4"),
                    InlineKeyboardButton(text="⭐ 5", callback_data=f"rate_{place_id}_5"),
                ],
                *([review_row] if review_row else []),
                photo_row,
                [InlineKeyboardButton(text="Обратно", callback_data=callback_data)],
            ]
        )

    @staticmethod
    async def _get_place_view_payload(
        db: AsyncDatabase,
        place_id: int,
        callback_data: str,
        search: str | None,
        user_id: int | None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        place = await db.places.get_place_by_id(place_id=place_id)
        if not place:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Обратно", callback_data=callback_data)],
                ]
            )
            return "⚠️ Место не найдено или было удалено.", keyboard

        place_name = place.get("name", "")
        full_address = place.get("full_address", "")
        flush_description_img_html = clean_html_to_text(place.get("description", ""))
        place_description = html.escape(flush_description_img_html)

        rating_avg = place.get("rating_avg", 0)
        rating_count = place.get("rating_count", 0)
        user_rating = None
        if user_id is not None:
            user_rating = await db.places.get_user_place_rating(place_id=place_id, user_id=user_id)
        reviews_count = await db.places.get_reviews_count(place_id=place_id)
        photos_count = await db.places.get_place_photos_count(place_id=place_id)

        html_place_description = PlacesView.__render_list_place_view(
            description=place_description,
            name=place_name,
            full_address=full_address,
            search=search,
            rating_avg=rating_avg,
            rating_count=rating_count,
            user_rating=user_rating,
            reviews_count=reviews_count,
            photos_count=photos_count,
        )
        keyboard = PlacesView._place_rating_keyboard(
            callback_data=callback_data,
            place_id=place_id,
            reviews_count=reviews_count,
            photos_count=photos_count,
        )
        return html_place_description, keyboard

    @staticmethod
    async def __message_ansver_places(
        message: Message,
        page_offset,
        pleces_count,
        answers,
        message_answer,
        line_count,
        search=None,
    ):
        page_state = PaginationControl(offset=page_offset, line_count=line_count, resource_count=pleces_count)
        keyboard = await PlacesView.__get_keyboard(buttons=[], page_state=page_state, start_line=page_offset)
        rendered_html = PlacesView.__render_list_places(answers=answers, message_answer=message_answer, search=search)
        await message.answer(text=rendered_html, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    @staticmethod
    async def get_all_places_slice(
        message: Message,
        page_offset: int,
        message_answer: str,
        db: AsyncDatabase,
        state: FSMContext,
        line_count,
    ):
        info = await state.get_data()
        location = info.get("location", None)
        pleces_count = await db.places.get_places_count()
        answers = await db.places.get_places(limit=line_count, offset=page_offset, location=location)
        await PlacesView.__message_ansver_places(
            message=message,
            page_offset=page_offset,
            pleces_count=pleces_count,
            answers=answers,
            message_answer=message_answer,
            line_count=line_count,
        )

    @staticmethod
    async def search_places_slice(
        message: Message,
        page_offset: int,
        search: str,
        message_answer: str,
        db: AsyncDatabase,
        elastic: ElasticPlacesIndexer,
        state: FSMContext,
        line_count,
    ):
        info = await state.get_data()
        places_ids = info.get("places_ids", None)
        location = info.get("location", None)
        if places_ids is None:
            places_ids = await elastic.search_place_ids(query=search)
            await state.update_data(places_ids=places_ids)
        result = await db.places.get_places_by_ids(ids=places_ids, limit=line_count, offset=page_offset, location=location)
        pleces_count = result["total"]
        answers = result["items"]
        await PlacesView.__message_ansver_places(
            message=message,
            page_offset=page_offset,
            pleces_count=pleces_count,
            answers=answers,
            message_answer=message_answer,
            search=search,
            line_count=line_count,
        )

    @staticmethod
    async def view_place_description(message, callback_data, place_id, db, search, user_id=None):
        html_place_description, keyboard = await PlacesView._get_place_view_payload(
            db=db,
            place_id=int(place_id),
            callback_data=callback_data,
            search=search,
            user_id=user_id,
        )
        await message.answer(
            parse_mode=ParseMode.HTML,
            text=html_place_description,
            reply_markup=keyboard,
        )

    @staticmethod
    async def edit_place_description(message, callback_data, place_id, db, search, user_id=None):
        html_place_description, keyboard = await PlacesView._get_place_view_payload(
            db=db,
            place_id=int(place_id),
            callback_data=callback_data,
            search=search,
            user_id=user_id,
        )
        if message.text is not None:
            await message.edit_text(
                parse_mode=ParseMode.HTML,
                text=html_place_description,
                reply_markup=keyboard,
            )
        else:
            await message.delete()
            await message.answer(
                parse_mode=ParseMode.HTML,
                text=html_place_description,
                reply_markup=keyboard,
            )

    @staticmethod
    async def edit_place_description_by_ids(
        bot: Bot,
        chat_id: int,
        message_id: int,
        callback_data,
        place_id,
        db,
        search,
        user_id=None,
    ):
        html_place_description, keyboard = await PlacesView._get_place_view_payload(
            db=db,
            place_id=int(place_id),
            callback_data=callback_data,
            search=search,
            user_id=user_id,
        )
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            parse_mode=ParseMode.HTML,
            text=html_place_description,
            reply_markup=keyboard,
        )

    @staticmethod
    def _build_reviews_text(total: int, items: list[dict]) -> str:
        lines = [f"💬 <b>Отзывы</b> ({total})"]
        if not items:
            lines.append("Пока нет отзывов.")
            return "\n".join(lines)

        for review in items:
            author = html.escape(review.get("user_name") or f"user_{review['user_id']}")
            raw_text = (review.get("text") or "").strip()
            if len(raw_text) > 500:
                raw_text = raw_text[:500] + "..."
            text = html.escape(raw_text)
            lines.append(f"\n• <b>{author}</b>\n{text}")
        return "\n".join(lines)

    @staticmethod
    def _build_reviews_keyboard(
        *,
        place_id: int,
        offset: int,
        total: int,
        items: list[dict],
        reviews_page_size: int,
        user_id: int | None,
        include_bulk_delete: bool,
        include_single_delete: bool,
    ) -> InlineKeyboardMarkup:
        keyboard_rows = []

        if include_bulk_delete:
            keyboard_rows.append(
                [
                    InlineKeyboardButton(
                        text="🗑 Удалить все мои отзывы",
                        callback_data=f"review_del_all_{place_id}_{offset}",
                    )
                ]
            )

        if include_single_delete and user_id is not None:
            for review in items:
                if review["user_id"] == user_id:
                    keyboard_rows.append(
                        [
                            InlineKeyboardButton(
                                text=f"🗑 Удалить отзыв #{review['id']}",
                                callback_data=f"review_del_{place_id}_{review['id']}_{offset}",
                            )
                        ]
                    )

        nav_row = []
        if offset > 0:
            nav_row.append(
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=f"review_show_{place_id}_{max(0, offset - reviews_page_size)}",
                )
            )
        if offset + reviews_page_size < total:
            nav_row.append(
                InlineKeyboardButton(
                    text="Вперёд ➡️",
                    callback_data=f"review_show_{place_id}_{offset + reviews_page_size}",
                )
            )
        if nav_row:
            keyboard_rows.append(nav_row)

        keyboard_rows.append(
            [InlineKeyboardButton(text="↩️ К карточке", callback_data=f"review_back_{place_id}")]
        )
        return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    @staticmethod
    async def edit_reviews_page(
        *,
        message: Message,
        db: AsyncDatabase,
        place_id: int,
        offset: int,
        reviews_page_size: int,
        user_id: int | None = None,
        include_bulk_delete: bool = True,
        include_single_delete: bool = False,
        normalize_offset: bool = False,
    ) -> None:
        offset = max(0, offset)
        if normalize_offset:
            total = await db.places.get_reviews_count(place_id=place_id)
            if total > 0 and offset >= total:
                offset = max(0, total - 1)

        page = await db.places.get_reviews_page(
            place_id=place_id,
            limit=reviews_page_size,
            offset=offset,
        )
        total = page["total"]
        items = page["items"]
        text = PlacesView._build_reviews_text(total=total, items=items)
        keyboard = PlacesView._build_reviews_keyboard(
            place_id=place_id,
            offset=offset,
            total=total,
            items=items,
            reviews_page_size=reviews_page_size,
            user_id=user_id,
            include_bulk_delete=include_bulk_delete,
            include_single_delete=include_single_delete,
        )
        if message.text is not None:
            await message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            await message.delete()
            await message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )

    @staticmethod
    def _build_photo_caption(photo: dict, offset: int, total: int) -> str:
        author = photo.get("user_name") or ("user_" + str(photo["user_id"]))
        user_caption = (photo.get("caption") or "").strip()
        if len(user_caption) > 900:
            user_caption = user_caption[:900] + "..."
        title = f"🖼 Фото {offset + 1}/{total}\nАвтор: {author}"
        return f"{title}\n\n{user_caption}" if user_caption else title

    @staticmethod
    def _build_photo_keyboard(place_id: int, offset: int, total: int) -> InlineKeyboardMarkup:
        nav_row = []
        if offset > 0:
            nav_row.append(
                InlineKeyboardButton(text="⬅️ Назад", callback_data=f"photo_show_{place_id}_{offset - 1}")
            )
        if offset + 1 < total:
            nav_row.append(
                InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"photo_show_{place_id}_{offset + 1}")
            )

        keyboard_rows = [
            [InlineKeyboardButton(text="🗑 Удалить все мои фото", callback_data=f"photo_del_all_{place_id}_{offset}")]
        ]
        if nav_row:
            keyboard_rows.append(nav_row)
        keyboard_rows.append([InlineKeyboardButton(text="↩️ К карточке", callback_data=f"photo_back_{place_id}")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    @staticmethod
    async def show_photos_page(message: Message, db: AsyncDatabase, place_id: int, offset: int) -> bool:
        offset = max(0, offset)
        page = await db.places.get_photos_page(place_id=place_id, limit=1, offset=offset)
        total = page["total"]
        items = page["items"]
        if total == 0 or not items:
            return False

        photo = items[0]
        caption = PlacesView._build_photo_caption(photo=photo, offset=offset, total=total)
        keyboard = PlacesView._build_photo_keyboard(place_id=place_id, offset=offset, total=total)

        if message.photo:
            await message.edit_media(
                media=InputMediaPhoto(media=photo["file_id"], caption=caption),
                reply_markup=keyboard,
            )
            return True

        try:
            await message.edit_media(
                media=InputMediaPhoto(media=photo["file_id"], caption=caption),
                reply_markup=keyboard,
            )
            return True
        except TelegramBadRequest:
            # На некоторых типах сообщений Telegram не дает заменить текст на media.
            # В таком случае оставляем запасной сценарий: отправка фото новой карточкой.
            await message.answer_photo(
                photo=photo["file_id"],
                caption=caption,
                reply_markup=keyboard,
            )
            try:
                await message.delete()
            except TelegramBadRequest:
                pass
        return True
