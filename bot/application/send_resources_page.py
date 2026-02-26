from aiogram.enums import ParseMode
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from infrastructure.db.PgDb import AsyncDatabase
from interface.handlers.keyboards.resources import get_resources_pagination_keyboard

# сколько ресурсов на одной странице

class ResourcePaginationMixin:
    async def fetch_resources_page(
        self,
        db: "AsyncDatabase",
        page: int,
        per_page: int | None = None
    ) -> tuple[list, int, int]:
        """
        Получаем данные для конкретной страницы.
        Возвращает (resources, current_page, total_pages).
        """
        if per_page is None:
            per_page = self.RESOURCES_PER_PAGE

        total_resources = await db.resources.get_resources_count()
        if total_resources == 0:
            return [], 0, 0

        total_pages = (total_resources + per_page - 1) // per_page
        # нормализуем страницу
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages

        offset = (page - 1) * per_page
        resources = await db.resources.get_resources(per_page, offset)
        return resources, page, total_pages


class ResourceRenderViewMixin:
    async def render_view_resources_page(
        self,
        resources: list,
        target: Message,
        page: int,
        total_pages: int,
        mode: str = "view"
    ):
        """
        Режим просмотра (все ресурсы в одном сообщении).
        """
        if not resources:
            await target.answer("📭 Ресурсов пока нет.")
            return

        text = "<b>📚 Список ресурсов:</b>\n\n"
        for res in resources:  # res: ResourceRow
            line = f"🔹 <b>{res['name']}</b> ({res['type']})\n"

            if res['description']:
                line += f"    <i>{res['description']}</i>\n"

            if res['url']:
                line += f"🌐 <a href='{res['url']}'>Ссылка</a>\n"

            text += line + "\n"

        pagination_kb = get_resources_pagination_keyboard(
            ResourcePageCallback=self.ResourcePageCallback,
            page=page,
            total_pages=total_pages,
            mode=mode
        )

        await target.answer(
            text=text + f"\nСтраница {page}/{total_pages}",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=pagination_kb
        )


class ResourceRenderDeleteMixin:
    async def render_delete_resources_page(
        self,
        resources: list,
        target: Message,
        page: int,
        total_pages: int,
        mode: str = "delete"
    ):
        """
        Режим удаления (отдельное сообщение на каждый ресурс).
        """
        if not resources:
            await target.answer("📭 Ресурсов для удаления нет.")
            return

        for resource in resources:
            res_id = resource["id"]
            name = resource["name"]
            type_ = resource["type"]
            description = resource.get("description")

            text = f"🔹 <b>{name}</b> ({type_})\n"
            if description:
                text += f"    <i>{description}</i>\n"

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(
                        text=f"❌ Удалить {name}",
                        callback_data=self.ResourceDeleteCallback(id=res_id).pack()
                    )
                ]]
            )

            await target.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=keyboard
            )

        # отдельное сообщение для пагинации
        pagination_kb = get_resources_pagination_keyboard(
            ResourcePageCallback=self.ResourceDeleteCallback,
            page=page,
            total_pages=total_pages,
            mode=mode
        )
        if pagination_kb:
            await target.answer(
                text=f"Страница {page}/{total_pages}",
                parse_mode=ParseMode.HTML,
                reply_markup=pagination_kb
            )


class ResourcePageHandler(ResourcePaginationMixin, ResourceRenderDeleteMixin, ResourceRenderViewMixin):
    def __init__(self, ResourcePageCallback=None, ResourceDeleteCallback=None, RESOURCES_PER_PAGE = 4):
        self.RESOURCES_PER_PAGE = RESOURCES_PER_PAGE
        self.ResourcePageCallback = ResourcePageCallback
        self.ResourceDeleteCallback = ResourceDeleteCallback

    async def send_resources_page(
        self,
        target: Message,
        db: AsyncDatabase,
        page: int,
        mode: str = "view"
    ):
        resources, page, total_pages = await self.fetch_resources_page(db, page)
        if mode == "view":
            await self.render_view_resources_page(
                resources=resources,
                target=target,
                page=page,
                total_pages=total_pages,
                mode=mode
            )
        elif mode == "delete":
            await self.render_delete_resources_page(
                resources=resources,
                target=target,
                page=page,
                total_pages=total_pages,
                mode=mode
            )
