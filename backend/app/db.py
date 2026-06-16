"""Async SQLAlchemy engine, session factory and Base.

Engine-agnostic: works on SQLite now, swappable to Postgres via db_url.
"""

from collections.abc import AsyncIterator

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.db_url, echo=False, future=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

# 非破坏性增量迁移（dev/SQLite）：{表: {列: 列定义SQL}}，缺则 ALTER ADD，保数据不丢。
_ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "rooms": {
        "world_card": "VARCHAR(32)",
        "week": "INTEGER DEFAULT 1",
        "day": "INTEGER DEFAULT 1",
        "time_slot": "INTEGER DEFAULT 0",
        "current_scene": "VARCHAR(64) DEFAULT ''",
        "scenes_meta": "TEXT",
    },
    "room_members": {
        "appearance": "VARCHAR(512)",
        "persona": "TEXT",
        "voice_id": "VARCHAR(200)",
        "voice_ref_url": "VARCHAR(256)",
        "voice_ref_text": "TEXT",
        "voice_variants": "TEXT",
        "avatar_url": "VARCHAR(256)",
        "avatar_variants": "TEXT",
        "stats": "TEXT",
    },
    "user_character_cards": {
        "voice_ref_url": "VARCHAR(256)",
        "voice_ref_text": "TEXT",
        "voice_variants": "TEXT",
        "avatar_url": "VARCHAR(256)",
        "avatar_variants": "TEXT",
        "source_world_card": "VARCHAR(32)",
    },
    "npc_cards": {
        "voice_ref_url": "VARCHAR(256)",
        "voice_ref_text": "TEXT",
        "voice_variants": "TEXT",
        "avatar_url": "VARCHAR(256)",
        "avatar_variants": "TEXT",
        "active": "BOOLEAN DEFAULT 1",
        "scene": "VARCHAR(64)",
        "discovered": "TEXT",
    },
}


def _apply_additive_migrations(sync_conn) -> None:
    insp = inspect(sync_conn)
    existing_tables = set(insp.get_table_names())
    for table, cols in _ADDITIVE_COLUMNS.items():
        if table not in existing_tables:
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        for col, ddl in cols.items():
            if col not in have:
                sync_conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


async def init_db() -> None:
    from . import models  # noqa: F401  ensure models are registered

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_additive_migrations)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
