"""API-owned schema entry point. Preserve deployed legacy revision IDs."""
from pathlib import Path
from alembic import command
from alembic.config import Config
from .config import Settings


def upgrade(url, revision='head'):
    root = Path(__file__).resolve().parents[2]
    config = Config()
    config.set_main_option('script_location', str(root / 'migrations'))
    config.attributes['database_url'] = url
    command.upgrade(config, revision)


def main():
    settings = Settings()
    upgrade(settings.database_url)
    print('Database migrations complete')


if __name__ == '__main__':
    main()
