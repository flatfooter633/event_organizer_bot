import asyncio
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import AsyncAdaptedQueuePool

from src.config.config import settings
from src.config.logger_config import logger
from src.database.models import Base

# ---------------------------------------------------------
# region engine
# ---------------------------------------------------------
engine = create_async_engine(
    url=settings.database.database_url_asyncpg,
    echo=False,  # Логирование SQL-запросов
    poolclass=AsyncAdaptedQueuePool,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
)
# endregion
# ---------------------------------------------------------


# Пример использования базы данных в асинхронном режиме
async def get_async_db_version():
    async with engine.connect() as async_conn:
        result = await async_conn.execute(text("SELECT VERSION()"))
        logger.info(f"PostgresSQL version: {result.fetchone()[0]}")


# Сессии для синхронного и асинхронного режима
async_session = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


if __name__ == "__main__":
    asyncio.run(get_async_db_version())
