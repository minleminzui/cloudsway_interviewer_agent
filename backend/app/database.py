from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings


engine = create_async_engine(settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:  # type: ignore[misc]
        yield session


async def init_models() -> None:
    from . import models  # noqa: WPS433

    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)


async def shutdown() -> None:
    await engine.dispose()
