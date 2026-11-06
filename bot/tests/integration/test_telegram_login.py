from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import text
from interface.handlers.telegram_login import website_login, confirm_website_login


@pytest.mark.asyncio
async def test_confirmation_requires_claiming_user(database):
    async with database.engine.begin() as c:
        await c.execute(text('DELETE FROM web_telegram_logins'))
        id = (await c.execute(text("INSERT INTO web_telegram_logins(browser_hash,link_hash,code,expires_at) VALUES ('browser',:hash,'123456',now()+interval '5 minutes') RETURNING id"), {'hash':sha256(b'nonce').hexdigest()})).scalar_one()
    message = SimpleNamespace(chat=SimpleNamespace(type='private'), text='/start login_nonce', from_user=SimpleNamespace(id=12345678901,full_name='Test'), answer=AsyncMock(),edit_text=AsyncMock())
    await website_login(message, database)
    assert '123456' in message.answer.call_args.args[0]
    callback = SimpleNamespace(message=message, data=f'web_login:yes:{id}',from_user=SimpleNamespace(id=999),answer=AsyncMock())
    await confirm_website_login(callback, database)
    assert callback.answer.call_args.kwargs['show_alert']
    async with database.engine.begin() as c:
        assert not (await c.execute(text('SELECT confirmed FROM web_telegram_logins WHERE id=:id'), {'id':id})).scalar_one()
    callback.from_user.id = 12345678901
    await confirm_website_login(callback, database)
    async with database.engine.begin() as c:
        assert (await c.execute(text('SELECT confirmed FROM web_telegram_logins WHERE id=:id'), {'id':id})).scalar_one()
    message.edit_text.assert_awaited_once()
