from infrastructure.db.PgDb import AsyncDatabase
# 🔑 Проверка роли
async def is_role(db: AsyncDatabase, tg_id: int, role: str) -> bool:
    user_role = await db.users.get_user_role(tg_id)  # предполагаем, что у тебя есть такой метод
    return user_role == role
