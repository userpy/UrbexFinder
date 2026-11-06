"""Explicit approval of browser login; no Telegram token leaves the server."""
from hashlib import sha256
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import text
from infrastructure.db.PgDb import AsyncDatabase

router=Router()


@router.message(Command('start'), F.text.regexp(r'^/start(?:@\w+)? login_[A-Za-z0-9_-]+$'))
async def website_login(message: Message, db: AsyncDatabase):
    if message.chat.type != 'private':return
    token=message.text.split('login_',1)[1]
    async with db.engine.begin() as c:
        row=(await c.execute(text('''UPDATE web_telegram_logins SET telegram_id=:user,display_name=:name
            WHERE link_hash=:hash AND expires_at>now() AND NOT consumed AND NOT confirmed
            AND (telegram_id IS NULL OR telegram_id=:user) RETURNING id,code'''),
            {'user':message.from_user.id,'name':message.from_user.full_name[:100],'hash':sha256(token.encode()).hexdigest()})).mappings().first()
    if not row:
        await message.answer('Ссылка входа недействительна или истекла. Начните вход заново на сайте.')
        return
    await message.answer(f"Вход на сайт UrbexFinder. Код: {row['code']}\nСверьте код со страницей сайта. Подтверждайте только вход, который начали сами. После подтверждения вернитесь в тот же браузер.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Подтвердить вход',callback_data=f"web_login:yes:{row['id']}"),InlineKeyboardButton(text='Отмена',callback_data=f"web_login:no:{row['id']}")]]))


@router.callback_query(F.data.regexp(r'^web_login:(yes|no):\d+$'))
async def confirm_website_login(callback: CallbackQuery, db: AsyncDatabase):
    if not callback.message or callback.message.chat.type != 'private':return
    _,decision,id=callback.data.split(':')
    async with db.engine.begin() as c:
        row=(await c.execute(text('''UPDATE web_telegram_logins SET confirmed=:confirm,consumed=:cancel
            WHERE id=:id AND telegram_id=:user AND expires_at>now() AND NOT consumed AND NOT confirmed RETURNING id'''),
            {'id':int(id),'user':callback.from_user.id,'confirm':decision=='yes','cancel':decision=='no'})).first()
    if not row:
        await callback.answer('Запрос истёк или уже обработан',show_alert=True);return
    await callback.answer()
    await callback.message.edit_text('Вход подтверждён. Вернитесь на сайт в тот же браузер.' if decision=='yes' else 'Вход отменён.')
