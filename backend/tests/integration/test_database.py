"""События и данные на уровне PostgreSQL: транзакционность уведомлений, сортировка ключей, миграции, журнал."""
import asyncio
from datetime import timedelta

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text, update

from app.db import SessionLocal, listen_dsn
from app.jobs.worker import cleanup_events
from app.models import Event, utcnow
from app.positions import key_between
from app.realtime.events import CHANNEL, publish
from tests.conftest import sync_engine

pytestmark = pytest.mark.integration


async def _notifications(action) -> list[str]:
    """Что услышит подписчик LISTEN, пока выполняется action."""
    async with await psycopg.AsyncConnection.connect(listen_dsn(), autocommit=True) as conn:
        await conn.execute(f"LISTEN {CHANNEL}")
        await action()
        return [n.payload async for n in conn.notifies(timeout=0.5)]


async def test_event_is_delivered_only_after_commit(db_session):
    async def commit():
        await publish(db_session, 7, "card.created", {"id": 1})
        await db_session.commit()

    payloads = await _notifications(commit)
    (event,) = (await db_session.scalars(select(Event))).all()
    assert payloads == [f"7:{event.id}"]


async def test_rolled_back_change_sends_no_event(db_session):
    """Изменение откатилось — подписчики не узнают о том, чего не было."""
    async def rollback():
        await publish(db_session, 7, "card.created", {"id": 1})
        await db_session.rollback()

    assert await _notifications(rollback) == []
    assert (await db_session.scalars(select(Event))).all() == []


async def test_postgres_sorts_position_keys_like_python(db_session):
    """COLLATE "C": с правилами сортировки языка «a» и «B» встали бы иначе, и порядок карточек поехал бы."""
    keys = [key_between(None, None)]
    for i in range(40):
        keys.insert(i % (len(keys) + 1), key_between(keys[i % (len(keys) + 1) - 1] if i % (len(keys) + 1) else None,
                                                     keys[i % (len(keys) + 1)] if i % (len(keys) + 1) < len(keys)
                                                     else None))
    keys += ["Z", "a", "B", "b", "A"]
    values = ", ".join(f"('{k}')" for k in keys)
    rows = await db_session.execute(text(
        f"SELECT k FROM (VALUES {values}) AS t(k) ORDER BY k COLLATE \"C\""))  # noqa: S608 — тестовые константы
    assert [r.k for r in rows] == sorted(keys)


async def test_old_events_are_cleaned_up(db_session):
    old = await publish(db_session, 1, "card.created", {})
    fresh = await publish(db_session, 1, "card.created", {})
    await db_session.commit()
    await db_session.execute(update(Event).where(Event.id == old.id).values(created_at=utcnow() - timedelta(days=2)))
    await db_session.commit()

    assert await cleanup_events(SessionLocal) == 1
    db_session.expire_all()
    assert [e.id for e in (await db_session.scalars(select(Event))).all()] == [fresh.id]


def test_migrations_go_down_and_up_cleanly():
    config = Config("alembic.ini")
    try:
        command.downgrade(config, "base")
        with sync_engine.connect() as conn:
            tables = conn.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")).scalar()
            types = conn.execute(text("SELECT count(*) FROM pg_type WHERE typname IN "
                                      "('job_status', 'board_role', 'export_status', 'thumbnail_status')")).scalar()
        assert tables == 1 and types == 0  # осталась только alembic_version, перечисления удалены
    finally:
        command.upgrade(config, "head")  # даже если проверка упала — остальным тестам нужна схема


async def test_concurrent_card_moves_into_one_slot_keep_every_card(db_session):
    """Двое одновременно кладут карточку в одно место: ключи могут совпасть, но ни одна карточка
    не пропадёт и порядок останется однозначным (при равных ключах — по id)."""
    from app.models import Board, BoardColumn, Card

    board = Board(title="Гонка")
    db_session.add(board)
    await db_session.flush()
    column = BoardColumn(board_id=board.id, title="A", position="V")
    db_session.add(column)
    await db_session.flush()
    first = Card(board_id=board.id, column_id=column.id, title="1", position="V")
    db_session.add(first)
    await db_session.commit()

    async def insert(title: str):
        async with SessionLocal() as session:
            session.add(Card(board_id=board.id, column_id=column.id, title=title,
                             position=key_between("V", None)))
            await session.commit()

    await asyncio.gather(insert("2"), insert("3"))
    rows = (await db_session.execute(
        select(Card.title).where(Card.column_id == column.id).order_by(Card.position, Card.id))).all()
    assert [r.title for r in rows] == ["1", "2", "3"]
