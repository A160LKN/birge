from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.database_url, pool_size=settings.db_pool_size,
                             max_overflow=settings.db_max_overflow, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def listen_dsn(url: str | None = None) -> str:
    """Адрес для отдельного соединения LISTEN.

    LISTEN не работает через пул соединений (PgBouncer в режиме транзакций): пул отдаёт серверное
    соединение другому клиенту, и уведомления молча теряются. У Neon пул — это хост с «-pooler»,
    а без этой части — прямое подключение к той же базе. Обычные запросы идут через пул, LISTEN — напрямую.
    """
    url = (url or settings.database_url).replace("postgresql+psycopg://", "postgresql://", 1)
    return url.replace("-pooler.", ".", 1)
