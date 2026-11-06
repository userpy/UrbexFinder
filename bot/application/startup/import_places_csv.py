"""Explicit CSV import; independent of startup seeding and external geocoding."""
import argparse
import asyncio
from infrastructure.core.settings import get_app_settings
from infrastructure.db.PgDb import AsyncDatabase
from application.startup.on_startup_places import seed_places_from_csv


async def run():
    parser=argparse.ArgumentParser()
    parser.add_argument('--path')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    s=get_app_settings()
    db=AsyncDatabase(pg_user=s.postgres_user,pg_password=s.postgres_password,pg_database=s.postgres_db,pg_host=s.postgres_host,pg_port=s.postgres_port)
    try:
        await db.connect()
        await seed_places_from_csv(db,args.path or s.places_csv_path,args.dry_run)
    finally:
        await db.close()


if __name__=='__main__':
    asyncio.run(run())
