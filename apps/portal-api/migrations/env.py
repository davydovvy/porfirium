import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config

from portal_api.config import settings
from portal_api.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def do_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = async_engine_from_config(config.get_section(config.config_ini_section))
    async with connectable.connect() as connection:
        await connection.run_sync(do_migrations)
    await connectable.dispose()


asyncio.run(run_async_migrations())

