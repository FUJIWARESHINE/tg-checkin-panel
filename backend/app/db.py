"""数据库连接与会话管理。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .logging_setup import logger
from .models import Base
from .settings import settings

settings.ensure_dirs()

engine = create_async_engine(
    settings.db_url,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _table_columns(conn: Connection, table: str) -> set[str]:
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _migrate(conn: Connection) -> None:
    """轻量迁移：create_all 只建新表，不会给已有的表补列。

    目前只涉及 tasks.account_ids（多账号同时执行）。老库补列后，用主账号回填，
    保证「一个任务一个账号」的历史数据在升级后行为不变。
    """
    if not _table_columns(conn, "tasks"):
        return

    if _table_columns(conn, "records") and "notify_status" not in _table_columns(conn, "records"):
        conn.exec_driver_sql("ALTER TABLE records ADD COLUMN notify_status VARCHAR(32) DEFAULT ''")
        logger.info("数据库迁移：records 表已新增 notify_status 列")

    if "account_ids" not in _table_columns(conn, "tasks"):
        conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN account_ids JSON DEFAULT '[]'")
        logger.info("数据库迁移：tasks 表已新增 account_ids 列")

    rows = conn.exec_driver_sql("SELECT id, account_id, account_ids FROM tasks").fetchall()
    backfilled = 0
    for task_id, account_id, raw in rows:
        if account_id is None:
            continue
        try:
            current = json.loads(raw) if isinstance(raw, (str, bytes)) and raw else raw
        except (ValueError, TypeError):
            current = None
        if isinstance(current, list) and current:
            continue
        conn.exec_driver_sql(
            "UPDATE tasks SET account_ids = ? WHERE id = ?",
            (json.dumps([int(account_id)]), task_id),
        )
        backfilled += 1
    if backfilled:
        logger.info("数据库迁移：%s 个任务的执行账号已回填为 account_ids", backfilled)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate)


async def dispose_db() -> None:
    await engine.dispose()


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖注入用。"""
    async with SessionLocal() as session:
        yield session
