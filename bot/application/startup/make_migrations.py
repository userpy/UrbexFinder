import asyncio


async def make_migrations() -> None:
    process = await asyncio.create_subprocess_exec(
        "alembic",
        "upgrade",
        "head",
    )
    return_code = await process.wait()
    if return_code != 0:
        raise RuntimeError(f"alembic upgrade failed with code {return_code}")
