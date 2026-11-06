"""One API-owned migration history, compatible with both legacy version tables."""
from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from urbex.bootstrap.config import Settings
from urbex.infrastructure.models import Base

config = context.config
engine = create_engine(config.attributes.get('database_url') or Settings().database_url)
try:
    with engine.begin() as connection:
        connection.execute(text('SELECT pg_advisory_xact_lock(734836209)'))
        tables = inspect(connection).get_table_names()
        # Existing bot databases already executed the legacy prefix. Adopt that
        # revision without replaying DDL or touching existing application data.
        if 'web_alembic_version' not in tables and 'alembic_version' in tables:
            versions = connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
            if len(versions) > 1:
                raise RuntimeError('Multiple legacy migration heads require manual reconciliation')
            if versions:
                ScriptDirectory.from_config(config).get_revision(versions[0])
                connection.execute(text('CREATE TABLE web_alembic_version (version_num varchar(32) PRIMARY KEY)'))
                connection.execute(text('INSERT INTO web_alembic_version VALUES (:revision)'), {'revision':versions[0]})
        context.configure(connection=connection, target_metadata=Base.metadata,
                          version_table='web_alembic_version', compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
